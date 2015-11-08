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

class InternetGateway(BotoResource):

    PROPERTIES = (
        TAGS,
    ) = (
        'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        TAGS: properties.Schema(
            properties.Schema.LIST,
            schema=properties.Schema(
                properties.Schema.MAP,
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
        internet_gateway = client.create_internet_gateway()

        if internet_gateway:
            self.resource_id_set(internet_gateway.id)

    def handle_delete(self):
        if self.resource_id is None:
            return

        client = self.vpc()
        client.delete_internet_gateway(self.resource_id)

class VPCGatewayAttachment(BotoResource):

    PROPERTIES = (
        VPC_ID, INTERNET_GATEWAY_ID, VPN_GATEWAY_ID,
    ) = (
        'VpcId', 'InternetGatewayId', 'VpnGatewayId',
    )

    properties_schema = {
        VPC_ID: properties.Schema(
            properties.Schema.STRING,
            _('VPC ID for this gateway association.'),
            required=True
        ),
        INTERNET_GATEWAY_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the InternetGateway.')
        ),
        VPN_GATEWAY_ID: properties.Schema(
            properties.Schema.STRING,
            _('ID of the VPNGateway to attach to the VPC.'),
        ),
    }

    def handle_create(self):
        client = self.vpc()

        vpc = self.properties.get(self.VPC_ID)
        internet_gateway = self.properties.get(self.INTERNET_GATEWAY_ID)
        vpn_gateway = self.properties.get(self.VPN_GATEWAY_ID)

        if internet_gateway:
            client.attach_internet_gateway(internet_gateway, vpc)

        if vpn_gateway:
            client.attach_vpn_gateway(vpn_gateway, vpc)

    def check_create_complete(self, *args):
        vpn_gateway_id = self.properties.get(self.VPN_GATEWAY_ID)
        vpn_gateways = self.vpc().get_all_vpn_gateways(vpn_connection_ids=[vpn_gateway_id])
        if vpn_gateways and len(vpn_gateways) > 0:
            status = vpn_gateways[0].state
            if status == 'attached':
                return True
        return False

    def handle_delete(self):
        client = self.vpc()

        vpc = self.properties.get(self.VPC_ID)
        internet_gateway = self.properties.get(self.INTERNET_GATEWAY_ID)
        vpn_gateway = self.properties.get(self.VPN_GATEWAY_ID)

        if internet_gateway:
            client.detach_internet_gateway(internet_gateway, vpc)

        if vpn_gateway:
            client.detach_vpn_gateway(vpn_gateway, vpc)

def resource_mapping():
    return {
        'OS::Heat::InternetGateway': InternetGateway,
        'OS::Heat::VPCGatewayAttachment': VPCGatewayAttachment,
    }
