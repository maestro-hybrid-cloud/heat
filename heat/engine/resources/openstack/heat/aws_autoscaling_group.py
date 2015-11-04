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

import boto.ec2
import boto.ec2.networkinterface

from oslo_log import log as logging

from heat.common import exception
from heat.common import grouputils
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import constraints
from heat.engine import function
from heat.engine import properties
from heat.engine.resources.aws.autoscaling import autoscaling_group as aws_asg

SERVERS_AWS_KEY = 'servers_aws'
LB_POOL_MEMBERS_KEY = 'lb_pool_members'

LOG = logging.getLogger(__name__)

class AWSAutoScalingGroup(aws_asg.AutoScalingGroup):

    PROPERTIES = (
        MAX_SIZE, MIN_SIZE, COOLDOWN, DESIRED_CAPACITY, ROLLING_UPDATES,
        LAUNCH_CONFIGURATION_NAME, SUBNET, LOADBALANCER_POOL, INSTANCE_ID,
        AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION_NAME,
        AWS_KEY_NAME, AWS_IMAGE_ID, AWS_INSTANCE_TYPE, AWS_SECURITY_GROUP, AWS_USER_DATA,
        AWS_SUBNET
    ) = (
        'max_size', 'min_size', 'cooldown', 'desired_capacity',
        'rolling_updates', 'launch_config_name', 'subnet', 'lb_pool', 'instance_id',
        'aws_access_key_id', 'aws_secret_access_key', 'aws_region_name',
        'aws_key_name', 'aws_image_id', 'aws_instance_type', 'aws_security_group',
        'aws_user_data', 'aws_subnet'
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
        AWS_ACCESS_KEY_ID: properties.Schema(
            properties.Schema.STRING,
            _('Access key ID of the AWS'),
            update_allowed=True,
        ),
        AWS_SECRET_ACCESS_KEY: properties.Schema(
            properties.Schema.STRING,
            _('Secret access key of the AWS'),
            update_allowed=True,
        ),
        AWS_REGION_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Region name of the AWS'),
            update_allowed=True,
        ),
        AWS_KEY_NAME: properties.Schema(
            properties.Schema.STRING,
            _('The reference to a LaunchConfiguration resource for AWS.'),
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

    def __init__(self, name, json_snippet, stack):
        super(AWSAutoScalingGroup, self).__init__(name, json_snippet, stack)
        self._local_context = None
        self._ec2_conn = None

    def ec2(self):
        if self._ec2_conn is None:
            self._ec2_conn = boto.ec2.connect_to_region(self.properties.get(self.AWS_REGION_NAME),
                                                        aws_access_key_id=self.properties.get(self.AWS_ACCESS_KEY_ID),
                                                        aws_secret_access_key=self.properties.get(self.AWS_SECRET_ACCESS_KEY))
        return self._ec2_conn

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
                data = '[]'
            return json.loads(data)

        if data_type == 'dict':
            if data is None:
                data = '{}'
            return json.loads(data)

        return data

    def _add_server_region_two(self, servers):
        servers_region_two = self._get_data(SERVERS_AWS_KEY, 'list')
        servers_region_two.append(servers)
        self._store_data(SERVERS_AWS_KEY, servers_region_two)

    def _pop_server_region_two(self):
        pop_server = None

        servers_region_two = self._get_data(SERVERS_AWS_KEY, 'list')
        pop_server = servers_region_two.pop()
        self._store_data(SERVERS_AWS_KEY, servers_region_two)

        return pop_server

    def _count_instances_region_two(self):
        servers_region_two = self._get_data(SERVERS_AWS_KEY, 'list')
        return len(servers_region_two)

    def _add_lb_pool_member(self, ip_address, new_member):
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

    def _get_conf_properties(self, aws=False):
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
            conf, props = super(AWSAutoScalingGroup, self)._get_conf_properties()

        region_one_subnet = self.properties.get(self.SUBNET)
        props['SubnetId'] = region_one_subnet

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
        allocated_ips = []
        member_ips = []

        for server in grouputils.get_members(self):
            server_ip = server.FnGetAtt('PublicIp') or server.FnGetAtt('PrivateIp')
            self.create_lb_pool_member(server_ip)
            allocated_ips.append(server_ip)

        pool_id = self.properties.get(self.LOADBALANCER_POOL)
        member_list = self.neutron().list_members(pool_id=pool_id)

        members = member_list.get('members')
        for member in members:
            member_ips.append(member.get('address'))

        for ip in member_ips:
            if not ip in allocated_ips:
                self.delete_lb_pool_member(ip)

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

        self._add_lb_pool_member(ip_address, new_member)

    def delete_lb_pool_member(self, ip_address):
        member_id = self._pop_lb_pool_member(ip_address)
        self.neutron().delete_member(member_id)

    def create_server_instances(self, num_create):
        instance_props = {
            'ImageId': self.properties.get(self.AWS_IMAGE_ID),
            'InstanceType': self.properties.get(self.AWS_INSTANCE_TYPE),
            'KeyName': self.properties.get(self.AWS_KEY_NAME),
            'UserData': self.properties.get(self.AWS_USER_DATA),
            'SubnetId': self.properties.get(self.AWS_SUBNET)
        }

        security_groups = []
        for security_group in self.properties.get(self.AWS_SECURITY_GROUP):
            security_groups.append(security_group)

        interface = boto.ec2.networkinterface.NetworkInterfaceSpecification(subnet_id=instance_props['SubnetId'],
                                                            groups=security_groups,
                                                            associate_public_ip_address=True)
        interfaces = boto.ec2.networkinterface.NetworkInterfaceCollection(interface)

        reservation = self.ec2().run_instances(
            image_id=instance_props['ImageId'],
            instance_type=instance_props['InstanceType'],
            key_name=instance_props['KeyName'],
            user_data=instance_props['UserData'],
            network_interfaces=interfaces,
            max_count=num_create
        )

        if reservation is not None:
            for instance in reservation.instances:
                self._add_server_region_two(instance.id)
                self.create_lb_pool_member(instance.private_ip_address)

    def delete_server_instances(self, num_create):
        count = num_create * -1

        LOG.debug('----del_count: %s', count)

        for i in range(count):
            server_id = self._pop_server_region_two()

            LOG.debug('----server_id: %s', server_id)

            servers = self.ec2().get_only_instances(instance_ids=[server_id])
            for server in servers:
                self.delete_lb_pool_member(server.private_ip_address)
                self.ec2().terminate_instances(instance_ids=[server.id])

    def check_create_complete(self, task):
        done = super(AWSAutoScalingGroup, self).check_create_complete(task)
        if done:
            self.refresh_lb_pool_members()
        return done

    def check_update_complete(self, cookie):
        done = super(AWSAutoScalingGroup, self).check_update_complete(cookie)
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
            old_resources = len(self._get_instance_templates()) \
                        + self._count_instances_region_two()
            num_create = capacity - old_resources
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
            super(AWSAutoScalingGroup, self).resize(new_capacity)

    def validate(self):
        instanceId = self.properties.get(self.INSTANCE_ID)
        launch_config = self.properties.get(
            self.LAUNCH_CONFIGURATION_NAME)
        if bool(instanceId) == bool(launch_config):
            msg = _("Either 'InstanceId' or 'LaunchConfigurationName' "
                    "must be provided.")
            raise exception.StackValidationFailed(message=msg)
        return super(AWSAutoScalingGroup, self).validate()

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

    def handle_delete(self):
        for k, v in self.data().items():
            self.data_delete(k)
        super(AWSAutoScalingGroup, self).handle_delete()

def resource_mapping():
    return {
        'OS::Heat::AWSAutoScalingGroup': AWSAutoScalingGroup,
    }
