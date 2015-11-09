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

import xml.etree.ElementTree as ET

from heat.engine import attributes
from heat.engine import properties
from heat.engine.resources.openstack.heat.aws import BotoResource

class VPNGateway(BotoResource):

    PROPERTIES = (
        TYPE, TAGS,
    ) = (
        'Type', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        TYPE: properties.Schema(
            properties.Schema.STRING,
        ),
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

        vpn_conn_type = self.properties.get(self.TYPE)
        vpn_gateway = client.create_vpn_gateway(vpn_conn_type)

        if vpn_gateway:
            self.resource_id_set(vpn_gateway.id)

    def handle_delete(self):
        if self.resource_id is None:
            return

        client = self.vpc()
        client.delete_vpn_gateway(self.resource_id)


class CustomerGateway(BotoResource):

    PROPERTIES = (
        TYPE, BGPASN, IP_ADDRESS, TAGS,
    ) = (
        'Type', 'BgpAsn', 'IpAddress', 'Tags',
    )

    _TAG_KEYS = (
        TAG_KEY, TAG_VALUE,
    ) = (
        'Key', 'Value',
    )

    properties_schema = {
        TYPE: properties.Schema(
            properties.Schema.STRING,
        ),
        BGPASN: properties.Schema(
            properties.Schema.STRING,
        ),
        IP_ADDRESS: properties.Schema(
            properties.Schema.STRING,
        ),
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

        vpn_conn_type = self.properties.get(self.TYPE)
        ip_address = self.properties.get(self.IP_ADDRESS)
        bgp_asn = self.properties.get(self.BGPASN)

        customer_gateway = client.create_customer_gateway(vpn_conn_type, ip_address, bgp_asn)
        if customer_gateway:
            self.resource_id_set(customer_gateway.id)

    def handle_delete(self):
        if self.resource_id is None:
            return

        client = self.vpc()
        client.delete_customer_gateway(self.resource_id)


class VPNConnection(BotoResource):

    PROPERTIES = (
        TYPE, STATIC_ROUTES_ONLY, CUSTOMER_GATEWAY_ID, VPN_GATEWAY_ID
    ) = (
        'Type', 'StaticRoutesOnly', 'CustomerGatewayId', 'VpnGatewayId'
    )

    ATTRIBUTES = (
        CUSTOMER_GATEWAY_CONFIGURATION, VPN_GATEWAY_IP_ADDRESS, IKE_PSK
    ) = (
        'CustomerGatewayConfiguration', 'VPNGatewayIPAddress', 'IKEPSK'
    )

    properties_schema = {
        TYPE: properties.Schema(
            properties.Schema.STRING,
        ),
        STATIC_ROUTES_ONLY: properties.Schema(
            properties.Schema.STRING,
        ),
        CUSTOMER_GATEWAY_ID: properties.Schema(
            properties.Schema.STRING,
        ),
        VPN_GATEWAY_ID: properties.Schema(
            properties.Schema.STRING,
        ),
    }

    attributes_schema = {
        CUSTOMER_GATEWAY_CONFIGURATION: attributes.Schema(),
        VPN_GATEWAY_IP_ADDRESS: attributes.Schema(),
        IKE_PSK: attributes.Schema(),
    }

    def _resolve_attribute(self, name):
        client = self.vpc()

        vpn_conns = client.get_all_vpn_connections(vpn_connection_ids=[self.resource_id])
        customer_gateway_config = vpn_conns[0].customer_gateway_configuration

        if name == self.CUSTOMER_GATEWAY_CONFIGURATION:
            return customer_gateway_config or ''

        xml_header = '<?xml version="1.0" encoding="UTF-8"?> '
        customer_gateway_config = customer_gateway_config.replace(xml_header, '')

        parsed_customer_gateway_config = ET.fromstring(customer_gateway_config)
        ipsec_tunnel_tag = parsed_customer_gateway_config.find('ipsec_tunnel')

        if name == self.IKE_PSK:
            ike_tag = ipsec_tunnel_tag.find('ike')
            pre_shared_key_tag = ike_tag.find('pre_shared_key')
            ike_psk = pre_shared_key_tag.text

            return ike_psk

        if name == self.VPN_GATEWAY_IP_ADDRESS:
            vpn_gateway_tag = ipsec_tunnel_tag.find('vpn_gateway')
            tunnel_outside_address_tag = vpn_gateway_tag.find('tunnel_outside_address')
            ip_address_tag = tunnel_outside_address_tag.find('ip_address')
            vpn_gateway_ip_address = ip_address_tag.text

            return vpn_gateway_ip_address

    def handle_create(self):
        client = self.vpc()

        vpn_conn_type = self.properties.get(self.TYPE)
        customer_gateway = self.properties.get(self.CUSTOMER_GATEWAY_ID)
        vpn_gateway = self.properties.get(self.VPN_GATEWAY_ID)
        static_routes_only = self.properties.get(self.STATIC_ROUTES_ONLY)

        vpn_connection = client.create_vpn_connection(vpn_conn_type, customer_gateway,
                                                      vpn_gateway, static_routes_only)

        if vpn_connection:
            self.resource_id_set(vpn_connection.id)

    def check_create_complete(self, *args):
        vpn_conns = self.vpc().get_all_vpn_connections(vpn_connection_ids=[self.resource_id])
        if vpn_conns and len(vpn_conns) > 0:
            status = vpn_conns[0].state
            if status == 'available':
                return True
        return False

    def handle_delete(self):
        if self.resource_id is None:
            return

        client = self.vpc()
        client.delete_vpn_connection(self.resource_id)

class VPNConnectionRoute(BotoResource):

    PROPERTIES = (
        VPN_CONNECTION_ID, DESTINATION_CIDR_BLOCK,
    ) = (
        'VpnConnectionId', 'DestinationCidrBlock'
    )

    properties_schema = {
        VPN_CONNECTION_ID: properties.Schema(
            properties.Schema.STRING,
        ),
        DESTINATION_CIDR_BLOCK: properties.Schema(
            properties.Schema.STRING,
        ),
    }

    def handle_create(self):
        client = self.vpc()

        destination_cidr_block = self.properties.get(self.DESTINATION_CIDR_BLOCK)
        vpn_connection = self.properties.get(self.VPN_CONNECTION_ID)

        client.create_vpn_connection_route(destination_cidr_block, vpn_connection)

    def handle_delete(self):
        if self.resource_id is None:
            return

        client = self.vpc()

        destination_cidr_block = self.properties.get(self.DESTINATION_CIDR_BLOCK)
        vpn_connection = self.properties.get(self.VPN_CONNECTION_ID)

        client.delete_vpn_connection_route(destination_cidr_block, vpn_connection)

def resource_mapping():
    return {
        'OS::Heat::VPNGateway': VPNGateway,
        'OS::Heat::CustomerGateway': CustomerGateway,
        'OS::Heat::VPNConnection': VPNConnection,
        'OS::Heat::VPNConnectionRoute': VPNConnectionRoute,
    }
