"""The primary REST route runs the same public behaviour contract as Graph."""
import unittest
from tests import test_cli as harness
from tests import test_organise as organisation
from outlooklib.client import normalise, rest_payload

REST = 'https://outlook.office.com/api/v2.0'
GRAPH = 'https://graph.microsoft.com/v1.0'


class RestMailbox(harness.FakeMailbox):
    def __call__(self, method, url, token, payload=None):
        # Synthetic external REST server: casing and OData names differ from Graph.
        graph_url = url.replace(REST, GRAPH).replace('InternetMessageId', 'internetMessageId')
        if url == REST + '/me':
            self.calls.append((method, url, payload))
            return {'Id': 'account', 'EmailAddress': 'owner@example.test'}
        data = super().__call__(method, graph_url, token, normalise(payload) if payload is not None else None)
        if '@odata.nextLink' in data:
            data['@odata.nextLink'] = data['@odata.nextLink'].replace(GRAPH, REST)
        return rest_payload(data)


class RestCliTest(harness.CliTest):
    def setUp(self):
        super().setUp()
        self.api = RestMailbox()

    def connect(self):
        code, result = self.call('connect', '--experimental', '--token-file', str(self.token), '--account', 'owner@example.test')
        self.assertEqual(code, 0, result)
        self.assertEqual(result['backend'], 'outlook-rest')
        return result


class RestOrganisationTest(organisation.OrganisationTest):
    def setUp(self):
        harness.CliTest.setUp(self)
        self.api = RestMailbox()

    connect = RestCliTest.connect


if __name__ == '__main__':
    unittest.main()
