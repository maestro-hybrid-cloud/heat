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

from heat.common.i18n import _
from heat.engine import properties
from heat.engine.resources.openstack.heat.aws import BotoResource
from heat.engine import support

class RouteTable(BotoResource):

    support_status = support.SupportStatus(version='2014.1')

    PROPERTIES = (
        VPC_ID, TAGS,
    ) = (
        'VpcId', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        VPC_ID: properties.Schema(
            properties.Schema.STRING,
            _('VPC ID for where the route table is created.'),
            required=True
        ),
        TAGS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
                _('List of tags to be attached to this resource.'),
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

    def handle_create(self):
        client = self.vpc()

        vpc = self.properties.get(self.VPC_ID)
        route_table = client.create_route_table(vpc)

        if route_table:
            self.resource_id_set(route_table.id)

    def handle_delete(self):
        client = self.vpc()
        client.delete_route_table(self.resource_id)


class SubnetRouteTableAssociation(BotoResource):

    PROPERTIES = (
        ROUTE_TABLE_ID, SUBNET_ID,
    ) = (
        'RouteTableId', 'SubnetId',
    )

    properties_schema = {
        ROUTE_TABLE_ID: properties.Schema(
            properties.Schema.STRING,
            _('Route table ID.'),
            required=True
        ),
        SUBNET_ID: properties.Schema(
            properties.Schema.STRING,
            _('Subnet ID.'),
            required=True,
        ),
    }

    def handle_create(self):
        client = self.vpc()

        route_table = self.properties.get(self.ROUTE_TABLE_ID)
        subnet = self.properties.get(self.SUBNET_ID)

        id = client.associate_route_table(route_table, subnet)
        if id:
            self.resource_id_set(id)

    def handle_delete(self):
        client = self.vpc()
        client.disassociate_route_table(self.resource_id)

class Route(BotoResource):

    PROPERTIES = (
        ROUTE_TABLE_ID, DESTINATION_CIDR_BLOCK, GATEWAY_ID, INSTANCE_ID,
        INTERFACE_ID, VPC_PEERING_CONNECTION_ID
    ) = (
        'RouteTableId', 'DestinationCidrBlock', 'GatewayId', 'InstanceId',
        'InterfaceId', 'VpcPeeringConnectionId'
    )

    properties_schema = {
        ROUTE_TABLE_ID: properties.Schema(
            properties.Schema.STRING,
        ),
        DESTINATION_CIDR_BLOCK: properties.Schema(
            properties.Schema.STRING,
        ),
        GATEWAY_ID: properties.Schema(
            properties.Schema.STRING,
        ),
        INSTANCE_ID: properties.Schema(
            properties.Schema.STRING,
        ),
        INTERFACE_ID: properties.Schema(
            properties.Schema.STRING,
        ),
        VPC_PEERING_CONNECTION_ID: properties.Schema(
            properties.Schema.STRING,
        ),
    }

    def handle_create(self):
        client = self.vpc()

        route_table = self.properties.get(self.ROUTE_TABLE_ID)
        destination_cidr_block = self.properties.get(self.DESTINATION_CIDR_BLOCK)
        gateway = self.properties.get(self.GATEWAY_ID)
        instance_id = self.properties.get(self.INSTANCE_ID)
        interface_id = self.properties.get(self.INTERFACE_ID)
        vpc_peering_connection = self.properties.get(self.VPC_PEERING_CONNECTION_ID)

        client.create_route(route_table, destination_cidr_block, gateway,
                                    instance_id, interface_id, vpc_peering_connection)

    def handle_delete(self):
        client = self.vpc()

        route_table = self.properties.get(self.ROUTE_TABLE_ID)
        destination_cidr_block = self.properties.get(self.DESTINATION_CIDR_BLOCK)

        client.delete_route(route_table, destination_cidr_block)

def resource_mapping():
    return {
        'OS::Heat::RouteTable': RouteTable,
        'OS::Heat::SubnetRouteTableAssociation': SubnetRouteTableAssociation,
        'OS::Heat::Route': Route,
    }
