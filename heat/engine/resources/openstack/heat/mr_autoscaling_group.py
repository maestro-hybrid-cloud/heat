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

import json
import uuid

from oslo_log import log as logging

from heat.common import context
from heat.common import exception
from heat.common import grouputils
from heat.common import template_format
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import function
from heat.engine import properties
from heat.engine import resource
from heat.engine import rsrc_defn
from heat.engine import scheduler
from heat.engine.resources.aws.autoscaling import autoscaling_group as aws_asg

lb_pool_member_resource = r'''
type: OS::Neutron::PoolMember
properties:
  pool_id: {pool_id}
  address: {ip_address}
  protocol_port: {protocol_port}
'''

SERVERS_REGION_TWO_KEY = 'servers_region_two'
LB_POOL_MEMBERS_KEY = 'lb_pool_members'

LOG = logging.getLogger(__name__)

class MultiRegionAutoScalingGroup(aws_asg.AutoScalingGroup):

    PROPERTIES = (
        MAX_SIZE, MIN_SIZE, COOLDOWN, DESIRED_CAPACITY, ROLLING_UPDATES,
        LAUNCH_CONFIGURATION_NAME, REGION_ONE_SUBNET, REGION_TWO_SUBNET, REGION_TWO_NAME,
        LOADBALANCER_POOL, INSTANCE_ID
    ) = (
        'max_size', 'min_size', 'cooldown', 'desired_capacity',
        'rolling_updates',
        'launch_config_name', 'subnet_region_one', 'subnet_region_two', 'region_two_name',
        'lb_pool', 'instance_id'
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
            # A default policy has all fields with their own default values.
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
            _('Name of the RegionTwo.'),
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

    def __init__(self, name, json_snippet, stack):
        super(MultiRegionAutoScalingGroup, self).__init__(name, json_snippet, stack)
        self._local_context = None

    def handle_create(self):
        super(MultiRegionAutoScalingGroup, self).handle_create()
        # self.data_set('servers_region_two', [])
        # self.data_set('lb_pool_members', {})

    def _store_data(self, key, value):
        if key is not unicode:
            key = str(key)
        if value is not unicode:
            value = json.dumps(value)
        self.data_set(key, value)

    def _get_data(self, key, data_type=None):
        data = self.data().get(key)

        if data_type == 'list':
            if data is None:
                data = []
            return json.loads(data)

        if data_type == 'dict':
            if data is None:
                data = {}
            return json.loads(data)

        return data

    def _add_servers_region_two(self, server):
        servers_region_two = self._get_data(SERVERS_REGION_TWO_KEY, 'list')
        servers_region_two.append(server.id)
        self._store_data(SERVERS_REGION_TWO_KEY, servers_region_two)

    def _pop_server_region_two(self):
        pop_server = None

        servers_region_two = self._get_data(SERVERS_REGION_TWO_KEY, 'list')
        pop_server = servers_region_two.pop()
        self._store_data(SERVERS_REGION_TWO_KEY, servers_region_two)

        return pop_server

    def _count_instances_region_two(self):
        servers_region_two = self._get_data(SERVERS_REGION_TWO_KEY, 'list')
        return len(servers_region_two)

    def _add_lb_pool_members(self, ip_address, new_member):
        lb_pool_members = self._get_data(LB_POOL_MEMBERS_KEY, 'dict')
        lb_pool_members.update({ip_address: new_member['member']['id']})
        self._store_data(LB_POOL_MEMBERS_KEY, lb_pool_members)

    def _pop_lb_pool_member(self, ip_address):
        pop_member = None
        lb_pool_members = self._get_data(LB_POOL_MEMBERS_KEY, 'dict')

        pop_member = lb_pool_members.get(ip_address)
        del lb_pool_members[ip_address]

        self._store_data(LB_POOL_MEMBERS_KEY, lb_pool_members)
        return pop_member

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
        props['SubnetId'] = region_one_subnet

        if region_two:
            region_two_subnet = self.properties.get(self.REGION_TWO_SUBNET)
            props['SubnetId'] = region_two_subnet

        return conf, props

    def _validate_lb_ip_address(self, ip_address):
        allocated_ips = []

        pool_id = self.properties.get(self.LOADBALANCER_POOL)
        member_list = self.neutron().list_members(pool_id=pool_id)

        members = member_list.get('members')
        for member in members:
            allocated_ips.append(member.get('address'))

        if ip_address in allocated_ips:
            return False
        return True

    def refresh_lb_pool_members(self):
        for server in grouputils.get_members(self):
            server_ip = server.FnGetAtt('PublicIp') or server.FnGetAtt('PrivateIp')
            self.create_lb_pool_member(server_ip)

    def create_lb_pool_member(self, ip_address):
        if not self._validate_lb_ip_address(ip_address):
            return

        new_member = self.neutron().create_member({
                                "member": {
                                    "pool_id": self.properties.get(self.LOADBALANCER_POOL),
                                    "admin_state_up": True,
                                    "protocol_port": "80",
                                    "address": ip_address
                                }})

        self._add_lb_pool_members(ip_address, new_member)

    def delete_lb_pool_member(self, ip_address):
        member_id = self._pop_lb_pool_member(ip_address)
        self.neutron().delete_member(member_id)

    def _build_nics(self, subnet_id):
        clients = self._context().clients
        neutron_client = clients.neutron()
        neutron_client_plugin = clients.client_plugin('neutron')

        network_id = neutron_client_plugin.network_id_from_subnet_id(subnet_id)
        if network_id:
            fixed_ip = {'subnet_id': subnet_id}
            port_props = {
                'admin_state_up': True,
                'network_id': network_id,
                'fixed_ips': [fixed_ip]
            }

            port = neutron_client.create_port({'port': port_props})['port']
            nics = [{'port-id': port['id']}]

            return nics
        return None

    def create_server_instances(self, num_create):
        clients = self._context().clients
        conf, props = self._get_conf_properties(region_two=True)

        subnet_id = props['SubnetId']
        nics = self._build_nics(subnet_id)
        image_id = clients.client_plugin('glance').get_image_id(props['ImageId'])
        key_id = clients.client_plugin('nova').get_flavor_id(props['InstanceType'])

        server = clients.nova().servers.create(
            name='%s%s' % (self.physical_resource_name(), uuid.uuid4()),
            image=image_id,
            flavor=key_id,
            key_name=props['KeyName'],
            user_data=props['UserData'],
            nics=nics,
            max_count=num_create
        )
        if server is not None:
            self._add_servers_region_two(server)

            def check_for_creation(server_id):
                while not connect_to_lb(server_id):
                    yield

            def connect_to_lb(server_id):
                server = self._context().clients.nova().servers.get(server_id)
                if server.status == 'ACTIVE':
                    first_network = server.addresses.items()[0][1]
                    first_network_info = first_network[0]
                    ip_address = first_network_info.get('addr')

                    self.create_lb_pool_member(ip_address)
                    return True
                return False

            checker = scheduler.TaskRunner(check_for_creation, server.id)
            checker(timeout=self.stack.timeout_secs())

    def delete_server_instances(self, num_create):
        count = num_create * -1
        for i in range(count):
            server_id = self._pop_server_region_two()

            server = self._context().clients.nova().servers.get(server_id)
            first_network = server.addresses.items()[0][1]
            first_network_info = first_network[0]
            ip_address = first_network_info.get('addr')

            self.delete_lb_pool_member(ip_address)
            self._context().clients.nova().servers.delete(server_id)

    def check_create_complete(self, task):
        done = super(MultiRegionAutoScalingGroup, self).check_create_complete(task)
        if done:
            self.refresh_lb_pool_members()
        return done

    def check_update_complete(self, cookie):
        done = super(MultiRegionAutoScalingGroup, self).check_update_complete(cookie)
        if done:
            self.refresh_lb_pool_members()
        return done

    def _resize(self, size_diff):
        if size_diff > 0:
            self.create_server_instances(size_diff)
        else:
            self.delete_server_instances(size_diff)

    def resize(self, new_capacity):
        def _get_size_diff(capacity):
            old_resources = self._get_instance_templates()
            num_create = capacity - len(old_resources)
            return num_create

        def _in_region_two(size_diff):
            if (size_diff > 0 and self._is_available_current_region()) or \
                    (size_diff <= 0 and self._count_instances_region_two() <= 0):\
                return False
            return True

        size_diff = _get_size_diff(new_capacity)
        if _in_region_two(size_diff):
            self._resize(size_diff)
        else:
            super(MultiRegionAutoScalingGroup, self).resize(new_capacity)

    def validate(self):
        instanceId = self.properties.get(self.INSTANCE_ID)
        launch_config = self.properties.get(
            self.LAUNCH_CONFIGURATION_NAME)
        if bool(instanceId) == bool(launch_config):
            msg = _("Either 'InstanceId' or 'LaunchConfigurationName' "
                    "must be provided.")
            raise exception.StackValidationFailed(message=msg)
        return super(MultiRegionAutoScalingGroup, self).validate()

    def _context(self):
        if self._local_context:
            return self._local_context

        self._region_name = self.properties.get(self.REGION_TWO_NAME)

        dict_ctxt = self.context.to_dict()
        dict_ctxt.update({'region_name': self._region_name})

        self._local_context = context.RequestContext.from_dict(dict_ctxt)
        return self._local_context

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
