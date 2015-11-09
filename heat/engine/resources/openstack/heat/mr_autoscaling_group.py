#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


from oslo_log import log as logging
from oslo_utils import excutils

import json
import six

from heat.common import exception
from heat.common import grouputils
from heat.common import template_format
from heat.common.i18n import _
from heat.common.i18n import _LI
from heat.common.i18n import _LE
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import environment
from heat.engine import function
from heat.engine import properties
from heat.engine import rsrc_defn
from heat.engine.resources.aws.autoscaling import autoscaling_group as aws_asg
from heat.engine.resources.aws.autoscaling.autoscaling_group import _calculate_new_capacity
from heat.scaling import template
from heat.engine import template as engine_template
from heat.engine.notification import autoscaling as notification

lb_pool_member_resource = r'''
type: OS::Neutron::PoolMember
properties:
  pool_id: {pool_id}
  address: {ip_address}
  protocol_port: {protocol_port}
'''

LOG = logging.getLogger(__name__)

class MultiRegionAutoScalingGroup(aws_asg.AutoScalingGroup):

    PROPERTIES = (
        MAX_SIZE, MIN_SIZE, COOLDOWN, DESIRED_CAPACITY, ROLLING_UPDATES,
        LAUNCH_CONFIGURATION_NAME, REGION_ONE_SUBNET, REGION_TWO_SUBNET,
        REGION_TWO_NAME, LOADBALANCER_POOL, INSTANCE_ID
    ) = (
        'max_size', 'min_size', 'cooldown', 'desired_capacity', 'rolling_updates',
        'launch_config_name', 'subnet_region_one', 'subnet_region_two',
        'region_two_name', 'lb_pool', 'instance_id'
    )

    _ROLLING_UPDATES_SCHEMA = (
        MIN_IN_SERVICE, MAX_BATCH_SIZE, PAUSE_TIME,
    ) = (
        'min_in_service', 'max_batch_size', 'pause_time',
    )

    ATTRIBUTES = (
        INSTANCE_LIST,
    ) = (
        'InstanceList',
    )

    properties_schema = {
        MAX_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Maximum number of resources in the group.'),
            required=True,
            update_allowed=True,
            constraints=[constraints.Range(min=0)],
        ),
        MIN_SIZE: properties.Schema(
            properties.Schema.INTEGER,
            _('Minimum number of resources in the group.'),
            required=True,
            update_allowed=True,
            constraints=[constraints.Range(min=0)]
        ),
        COOLDOWN: properties.Schema(
            properties.Schema.INTEGER,
            _('Cooldown period, in seconds.'),
            update_allowed=True
        ),
        DESIRED_CAPACITY: properties.Schema(
            properties.Schema.INTEGER,
            _('Desired initial number of resources.'),
            update_allowed=True
        ),
        ROLLING_UPDATES: properties.Schema(
            properties.Schema.MAP,
            _('Policy for rolling updates for this scaling group.'),
            required=False,
            update_allowed=True,
            schema={
                MIN_IN_SERVICE: properties.Schema(
                    properties.Schema.NUMBER,
                    _('The minimum number of resources in service while '
                      'rolling updates are being executed.'),
                    constraints=[constraints.Range(min=0)],
                    default=0),
                MAX_BATCH_SIZE: properties.Schema(
                    properties.Schema.NUMBER,
                    _('The maximum number of resources to replace at once.'),
                    constraints=[constraints.Range(min=0)],
                    default=1),
                PAUSE_TIME: properties.Schema(
                    properties.Schema.NUMBER,
                    _('The number of seconds to wait between batches of '
                      'updates.'),
                    constraints=[constraints.Range(min=0)],
                    default=0),
            },
            default={
                MIN_IN_SERVICE: 0,
                MAX_BATCH_SIZE: 1,
                PAUSE_TIME: 0,
            },
        ),
        LAUNCH_CONFIGURATION_NAME: properties.Schema(
            properties.Schema.STRING,
            _('The reference to a LaunchConfiguration resource.'),
            update_allowed=True,
        ),
        REGION_ONE_SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('Subnet resource of the RegionOne'),
            update_allowed=True,
        ),
        REGION_TWO_SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('Subnet resource of the RegionTwo'),
            update_allowed=True,
        ),
        REGION_TWO_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Name of the RegionTwo'),
            update_allowed=True,
        ),
        INSTANCE_ID: properties.Schema(
            properties.Schema.STRING,
            _('The ID of an existing instance to use to '
              'create the Auto Scaling group. If specify this property, '
              'will create the group use an existing instance instead of '
              'a launch configuration.'),
            update_allowed=True,
        ),
        LOADBALANCER_POOL: properties.Schema(
            properties.Schema.STRING,
            _('Pool resource of the load balancer'),
            update_allowed=True,
        ),
    }

    attributes_schema = {
        INSTANCE_LIST: attributes.Schema(
            _("A comma-delimited list of server ip addresses. "
              "(Heat extension).")
        ),
    }

    def _make_remote_stack_definition(self, region_name, template, name):
        rs_res_type = 'OS::Heat::Stack'
        props = {
            'context':  { 'region_name': region_name },
            'template': template
        }
        rs_res_def = rsrc_defn.ResourceDefinition(name,
                                                  rs_res_type,
                                                  props)
        return rs_res_def

    def _make_template_resource_snippet(self, name, type, properties, outputs):
        json_snippet = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {},
            'Resources': {
                name: {
                    'Type': type,
                    'Properties': properties
                }
            },
            'Outputs': outputs
        }
        return json.dumps(json_snippet)

    def _get_conf_properties(self, region_two=False):
        instance_id = self.properties.get(self.INSTANCE_ID)
        if instance_id:
            server = self.client_plugin('nova').get_server(instance_id)
            instance_props = {
                'ImageId': server.image['id'],
                'InstanceType': server.flavor['id'],
                'KeyName': server.key_name,
                'SecurityGroups': [sg['name']
                                   for sg in server.security_groups],
                'UserData': server.user_data
            }
            conf = self._make_launch_config_resource(self.name,
                                                     instance_props)
            props = function.resolve(conf.properties.data)
        else:
            conf, props = super(MultiRegionAutoScalingGroup, self)._get_conf_properties()

        region_one_subnet = self.properties.get(self.REGION_ONE_SUBNET)
        if region_one_subnet:
            props['SubnetId'] = region_one_subnet

        if region_two:
            region_two_subnet = self.properties.get(self.REGION_TWO_SUBNET)
            if region_two_subnet:
                props['SubnetId'] = region_two_subnet

        return conf, props

    def _get_instance_definition(self):
        if self._is_available_current_region():
            return super(MultiRegionAutoScalingGroup, self)._get_instance_definition()
        else:
            conf, props = self._get_conf_properties(region_two=True)
            rsrc = rsrc_defn.ResourceDefinition(None,
                                                'AWS::EC2::Instance',
                                                props,
                                                conf.t.metadata())
            templ = self._make_template_resource_snippet('server', rsrc['Type'], rsrc['Properties'],
                                                         {
                                                             'PrivateIp':
                                                              {
                                                                  "Value": {
                                                                      "Fn::GetAtt": ["server", "PrivateIp"]
                                                                  },
                                                                  "Description": ""
                                                              }
                                                         })

            return self._make_remote_stack_definition(self.properties.get(self.REGION_TWO_NAME),
                                                      templ, None)


    def _create_instance_template(self, num_instances, num_replace):
        instance_definition = self._get_instance_definition()
        old_resources = self._get_instance_templates()
        definitions = template.resource_templates(
            old_resources, instance_definition, num_instances, num_replace)

        return definitions

    def adjust(self, adjustment, adjustment_type):
        """
        Adjust the size of the scaling group if the cooldown permits.
        """
        if self._cooldown_inprogress():
            LOG.info(_LI("%(name)s NOT performing scaling adjustment, "
                         "cooldown %(cooldown)s"),
                     {'name': self.name,
                      'cooldown': self.properties[self.COOLDOWN]})
            return

        capacity = self._get_instances_count()
        lower = self.properties[self.MIN_SIZE]
        upper = self.properties[self.MAX_SIZE]

        new_capacity = _calculate_new_capacity(capacity, adjustment,
                                               adjustment_type, lower, upper)

        # send a notification before, on-error and on-success.
        notif = {
            'stack': self.stack,
            'adjustment': adjustment,
            'adjustment_type': adjustment_type,
            'capacity': capacity,
            'groupname': self.FnGetRefId(),
            'message': _("Start resizing the group %(group)s") % {
                'group': self.FnGetRefId()},
            'suffix': 'start',
        }
        notification.send(**notif)
        try:
            self.resize(new_capacity)
        except Exception as resize_ex:
            with excutils.save_and_reraise_exception():
                try:
                    notif.update({'suffix': 'error',
                                  'message': six.text_type(resize_ex),
                                  })
                    notification.send(**notif)
                except Exception:
                    LOG.exception(_LE('Failed sending error notification'))
        else:
            notif.update({
                'suffix': 'end',
                'capacity': new_capacity,
                'message': _("End resizing the group %(group)s") % {
                    'group': notif['groupname']},
            })
            notification.send(**notif)
        finally:
            self._cooldown_timestamp("%s : %s" % (adjustment_type,
                                                  adjustment))

    def _create_template(self, num_instances, num_replace=0,
                     template_version=('HeatTemplateFormatVersion',
                                       '2013-05-23')):

        instance_definitions = self._create_instance_template(num_instances, num_replace)

        template = {
            'HeatTemplateFormatVersion': '2012-12-12',
            'Parameters': {},
            'Resources': {},
            'Outputs': {}
        }

        def template_resource(name, defn):
            return  {
                name: {
                    'Type': defn.get('Type') or defn.get('type'),
                    'Properties': defn.get('Properties') or defn.get('properties')
                }
            }

        for name, defn in instance_definitions:
            template['Resources'].update(template_resource(name, defn))

            lb_address = '{ "Fn::GetAtt" : [ "%s", "PrivateIp" ]}' % name
            if defn['Type'] == 'OS::Heat::Stack':
                lb_address = '{ "Fn::Select" : [ "PrivateIp", { "Fn::GetAtt" : [ "%s" ,"outputs" ]} ] }' % name

            rsrc = template_format.simple_parse(lb_pool_member_resource.format(
                pool_id=self.properties.get(self.LOADBALANCER_POOL),
                ip_address=lb_address,
                protocol_port='80'
            ))

            template['Resources'].update(template_resource('lb-%s' % name, rsrc))

        child_env = environment.get_child_environment(
            self.stack.env,
            self.child_params(), item_to_remove=self.resource_info)

        return engine_template.Template(template, env=child_env)

    def _get_instances_count(self):
        if self.nested():
            resources = [r for r in six.itervalues(self.nested())
                         if r.status != r.FAILED and
                         (r.type() == 'OS::Heat::ScaledResource' or
                          r.type() == 'OS::Heat::Stack')]   
            return len(resources)
        else:
            return 0

    def _get_instance_templates(self):
        instance_resources = []
        for member in grouputils.get_members(self):
            if member.type() == 'OS::Heat::Stack':
                instance_resources.append((member.name, member.t))

        for member in grouputils.get_members(self):
            if member.type() == 'OS::Heat::ScaledResource':
                instance_resources.append((member.name, member.t))
        return instance_resources

    def validate(self):
        instanceId = self.properties.get(self.INSTANCE_ID)
        launch_config = self.properties.get(
            self.LAUNCH_CONFIGURATION_NAME)
        if bool(instanceId) == bool(launch_config):
            msg = _("Either 'InstanceId' or 'LaunchConfigurationName' "
                    "must be provided.")
            raise exception.StackValidationFailed(message=msg)
        return super(MultiRegionAutoScalingGroup, self).validate()

    def _is_available_current_region(self):
        limits = self.nova().limits.get(reserved=True).absolute

        limits_dict = {}
        for limit in limits:
            if limit.value < 0:
                if limit.name.startswith('total') and limit.name.endswith('Used'):
                    limits_dict[limit.name] = 0
                else:
                    limits_dict[limit.name] = float("inf")
            else:
                limits_dict[limit.name] = limit.value

        def is_available_instances(limits):
            return True if limits['maxTotalInstances'] - limits['totalInstancesUsed'] > 0 else False

        def is_available_cpus(limits):
            return True if limits['maxTotalCores'] - limits['totalCoresUsed'] > 0 else False

        def is_available_memory(limits):
            return True if limits['maxTotalRAMSize'] - limits['totalRAMUsed'] > 0 else False

        return is_available_instances(limits_dict) and is_available_cpus(limits_dict) and\
                    is_available_memory(limits_dict)

def resource_mapping():
    return {
        'OS::Heat::MultiRegionAutoScalingGroup': MultiRegionAutoScalingGroup,
    }
