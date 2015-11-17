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

import six

from oslo_log import log as logging

from heat.common import grouputils
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import properties
from heat.engine import rsrc_defn
from heat.engine.resources.openstack.heat.mr_autoscaling_group import MultiRegionAutoScalingGroup

LOG = logging.getLogger(__name__)

class AWSHybridAutoScalingGroup(MultiRegionAutoScalingGroup):

    PROPERTIES = (
        MAX_SIZE, MIN_SIZE, COOLDOWN, DESIRED_CAPACITY, ROLLING_UPDATES,
        LAUNCH_CONFIGURATION_NAME, SUBNET, LOADBALANCER_POOL, INSTANCE_ID,
        AWS_KEY_NAME, AWS_IMAGE_ID, AWS_INSTANCE_TYPE,
        AWS_SECURITY_GROUP, AWS_USER_DATA, AWS_SUBNET
    ) = (
        'max_size', 'min_size', 'cooldown', 'desired_capacity', 'rolling_updates',
        'launch_config_name', 'subnet', 'lb_pool', 'instance_id',
        'aws_key_name', 'aws_image_id', 'aws_instance_type',
        'aws_security_group', 'aws_user_data', 'aws_subnet'
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
        SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('Subnet resource of the RegionOne'),
            update_allowed=True,
        ),
        LOADBALANCER_POOL: properties.Schema(
            properties.Schema.STRING,
            _('Pool resource of the load balancer'),
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
        AWS_KEY_NAME: properties.Schema(
            properties.Schema.STRING,
            _('The reference to a LaunchConfiguration resource for AWS'),
            update_allowed=True,
        ),
        AWS_IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _('AWS image ID'),
            update_allowed=True,
        ),
        AWS_INSTANCE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('AWS instance type'),
            update_allowed=True,
        ),
        AWS_SECURITY_GROUP: properties.Schema(
            properties.Schema.LIST,
            _('AWS security group'),
            update_allowed=True,
        ),
        AWS_USER_DATA: properties.Schema(
            properties.Schema.STRING,
            _('AWS EC2 user data'),
            update_allowed=True,
        ),
        AWS_SUBNET: properties.Schema(
            properties.Schema.STRING,
            _('Subnet resource of the AWS'),
            update_allowed=True,
        ),
    }

    attributes_schema = {
        INSTANCE_LIST: attributes.Schema(
            _("A comma-delimited list of server ip addresses. "
              "(Heat extension).")
        ),
    }

    def _get_conf_properties(self):
        conf, props = super(AWSHybridAutoScalingGroup, self)._get_conf_properties()
        props['SubnetId'] = self.properties.get(self.SUBNET)

        return conf, props

    def _get_instance_definition(self):
        if self._is_available_current_region():
            return super(AWSHybridAutoScalingGroup, self)._get_instance_definition()
        else:
            conf, props = self._get_conf_properties()

            instance_props = {
                'image_id': self.properties.get(self.AWS_IMAGE_ID),
                'instance_type': self.properties.get(self.AWS_INSTANCE_TYPE),
                'key_name': self.properties.get(self.AWS_KEY_NAME),
                'user_data': self.properties.get(self.AWS_USER_DATA),
                'subnet_id': self.properties.get(self.AWS_SUBNET),
                'monitoring': True,
                'Tags': self._tags()
            }

            security_groups = self.properties.get(self.AWS_SECURITY_GROUP)
            if security_groups:
                instance_props['security_groups'] = [sg for sg in security_groups]

            return rsrc_defn.ResourceDefinition(None,
                                                'AWS::VPC::EC2Instance',
                                                instance_props,
                                                conf.t.metadata())

    def _get_instances_count(self):
        if self.nested():
            resources = [r for r in six.itervalues(self.nested())
                         if r.status != r.FAILED and
                         (r.type() == 'OS::Heat::ScaledResource' or
                          r.type() == 'AWS::VPC::EC2Instance')]
            return len(resources)
        else:
            return 0

    def _get_instance_templates(self):
        instance_resources = []
        for member in grouputils.get_members(self):
            if member.type() == 'AWS::VPC::EC2Instance':
                instance_resources.append((member.name, member.t))

        for member in grouputils.get_members(self):
            if member.type() == 'OS::Heat::ScaledResource':
                instance_resources.append((member.name, member.t))
        return instance_resources

def resource_mapping():
    return {
        'OS::Heat::AWSHybridAutoScalingGroup': AWSHybridAutoScalingGroup,
    }
