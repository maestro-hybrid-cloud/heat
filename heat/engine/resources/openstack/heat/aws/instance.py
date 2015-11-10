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

import boto.ec2.networkinterface

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import properties
from heat.engine.resources.openstack.heat.aws import BotoResource

LOG = logging.getLogger(__name__)

class EC2Instance(BotoResource):

    PROPERTIES = (
        IMAGE_ID, INSTANCE_TYPE, KEY_NAME, SECURITY_GROUPS, SUBNET_ID,
        USER_DATA, MONITORING
    ) = (
        'image_id', 'instance_type', 'key_name', 'security_groups', 'subnet_id',
        'user_data', 'monitoring'
    )

    ATTRIBUTES = (
        PRIVATE_IP, PUBLIC_IP,
    ) = (
        'PrivateIp', 'PublicIp',
    )

    properties_schema = {
        IMAGE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Image ID or name.'),
            required=True
        ),
        INSTANCE_TYPE: properties.Schema(
            properties.Schema.STRING,
            _('Instance type (flavor).'),
            required=True,
            update_allowed=True,
        ),
        KEY_NAME: properties.Schema(
            properties.Schema.STRING,
            _('Keypair name.'),
        ),
        SECURITY_GROUPS: properties.Schema(
            properties.Schema.LIST,
            _('Security group names to assign.')
        ),
        SUBNET_ID: properties.Schema(
            properties.Schema.STRING,
            _('Subnet ID to launch instance in.'),
            update_allowed=True
        ),
        USER_DATA: properties.Schema(
            properties.Schema.STRING,
            _('User data to pass to instance.')
        ),
        MONITORING: properties.Schema(
            properties.Schema.BOOLEAN,
            _('Enable detailed CloudWatch monitoring on the instance.'),
            default=False
        ),
    }

    attributes_schema = {
        PRIVATE_IP: attributes.Schema(
            _('Private IP address of the specified instance.')
        ),
        PUBLIC_IP: attributes.Schema(
            _('Public IP address of the specified instance.')
        ),
    }

    def _resolve_attribute(self, name):
        ipaddress = '0.0.0.0'
        client = self.ec2()

        if name == self.PRIVATE_IP:
            servers = client.get_only_instances(instance_ids=[self.resource_id])
            private_ip_address = servers[0].private_ip_address
            if private_ip_address:
                ipaddress = private_ip_address

        if name == self.PUBLIC_IP:
            servers = client.get_only_instances(instance_ids=[self.resource_id])
            public_ip_address = servers[0].public_ip_address
            if public_ip_address:
                ipaddress = public_ip_address

        return ipaddress

    def handle_create(self):
        client = self.ec2()

        userdata = self.properties.get(self.USER_DATA) or ''
        flavor = self.properties[self.INSTANCE_TYPE]
        image_name = self.properties[self.IMAGE_ID]
        subnet_id = self.properties.get(self.SUBNET_ID)
        security_groups = self.properties.get(self.SECURITY_GROUPS)
        monitoring = self.properties.get(self.MONITORING)

        reservation = None

        if subnet_id and security_groups:
            interface = boto.ec2.networkinterface.NetworkInterfaceSpecification(
                                                        subnet_id=subnet_id,
                                                        groups=security_groups,
                                                        associate_public_ip_address=True)
            interfaces = boto.ec2.networkinterface.NetworkInterfaceCollection(interface)

            reservation = client.run_instances(
                        image_id=image_name,
                        instance_type=flavor,
                        key_name=self.properties[self.KEY_NAME],
                        user_data=userdata,
                        network_interfaces=interfaces,
                        monitoring_enabled=monitoring)
        else:
            reservation = client.run_instances(
                        image_id=image_name,
                        instance_type=flavor,
                        key_name=self.properties[self.KEY_NAME],
                        user_data=userdata,
                        monitoring_enabled=monitoring)

        if reservation is not None:
            for instance in reservation.instances:
                self.resource_id_set(instance.id)

    def check_create_complete(self, cookie):
        return (self._check_active(self.resource_id))

    def _check_active(self, server_id):
        instances = self.ec2().get_only_instances(instance_ids=[server_id])
        if instances and len(instances) > 0:
            status = instances[0].state
            if status == 'running':
                return True
        return False

    def handle_check(self):
        if not self._check_active(self.resource_id):
            raise exception.Error(_("Instance is not running"))

    def handle_delete(self):
        if self.resource_id is None:
            return
        self.ec2().terminate_instances(instance_ids=[self.resource_id])

def resource_mapping():
    return {
        'OS::Heat::EC2Instance': EC2Instance,
    }
