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

import boto.ec2
import boto.ec2.networkinterface

from heat.common import exception
from heat.common.i18n import _
from heat.engine import attributes
from heat.engine import properties
from heat.engine.resources.openstack.heat.aws import BotoResource


class Subnet(BotoResource):

    PROPERTIES = (
        AVAILABILITY_ZONE, CIDR_BLOCK, VPC_ID, TAGS,
    ) = (
        'AvailabilityZone', 'CidrBlock', 'VpcId', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    ATTRIBUTES = (
        AVAILABILITY_ZONE,
    )

    properties_schema = {
        AVAILABILITY_ZONE: properties.Schema(
            properties.Schema.STRING,
            _('Availability zone in which you want the subnet.')
        ),
        CIDR_BLOCK: properties.Schema(
            properties.Schema.STRING,
            _('CIDR block to apply to subnet.'),
            required=True
        ),
        VPC_ID: properties.Schema(
            properties.Schema.STRING,
            _('Ref structure that contains the ID of the VPC on which you '
              'want to create the subnet.'),
            required=True
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of tags to attach to this resource.'),
                schema={
                    TAG_KEY: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                    TAG_VALUE: properties.Schema(
                        properties.Schema.STRING,
                        required=True
                    ),
                },
                implemented=False,
            )
        ),
    }

    attributes_schema = {
        AVAILABILITY_ZONE: attributes.Schema(
            _('Availability Zone of the subnet.')
        ),
    }

    default_client_name = 'neutron'

    def handle_create(self):
        client = self.vpc()

        vpc_id = self.properties.get(self.VPC_ID)
        cidr_block = self.properties.get(self.CIDR_BLOCK)
        availablity_zone = self.properties.get(self.AVAILABILITY_ZONE)

        subnet = client.create_subnet(vpc_id, cidr_block, availablity_zone)
        if subnet:
            self.resource_id_set(subnet.id)

    def handle_delete(self):
        if self.resource_id is None:
            return

        client = self.vpc()
        client.delete_subnet(self.resource_id)

    def _resolve_attribute(self, name):
        if name == self.AVAILABILITY_ZONE:
            return self.properties.get(self.AVAILABILITY_ZONE)

def resource_mapping():
    return {
        'OS::Heat::Subnet': Subnet,
    }