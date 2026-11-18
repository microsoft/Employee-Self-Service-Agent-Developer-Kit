# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Public Graph beta profile fixtures, verified against the CSDL and live shapes."""

from uuid import UUID

MOCK_STATUS = "validatable"
MOCK_SCHEMA_SOURCE = "https://graph.microsoft.com/beta/$metadata"
GRAPH_BASE = "https://graph.microsoft.com/beta"


def directory_user(index=1):
    return {"id": str(UUID(int=index)), "userType": "Member"}


def profile():
    """Selected business fields and standard profile sections.

    Source (validatable): https://graph.microsoft.com/beta/$metadata
      profile: account/names/positions and other section navigation collections.
      userAccountInformation.userPrincipalName, personName.displayName/first/last:
        Edm.String. workPosition.isCurrent: Edm.Boolean.
      itemEmail.address: Edm.String; emailType: unknown, work, personal, main, other.
      positionDetail.layer: Edm.Int32; startMonthYear/endMonthYear: Edm.Date;
        remaining selected scalar detail/company/address fields: Edm.String.
      relatedPerson.userId: Edm.String; workPosition.colleagues: collection.
      profile.anniversaries: Collection(personAnnualEvent); date: Edm.Date;
        personAnnualEventType: birthday, wedding, work, other, unknownFutureValue.
      profile section types verified in the same schema.
    Docs/examples:
      https://learn.microsoft.com/en-us/graph/api/profile-get?view=graph-rest-beta#examples
      https://learn.microsoft.com/en-us/graph/api/resources/positiondetail?view=graph-rest-beta
      https://learn.microsoft.com/en-us/graph/api/resources/companydetail?view=graph-rest-beta
    The singular account collection matches both the CSDL and live beta output.
    """
    return {
        "id": "test-profile",
        "account": [{"userPrincipalName": "maker@example.test"}],
        "names": [{"displayName": "Test Maker", "first": "Test", "last": "Maker"}],
        "positions": [{
            "isCurrent": True,
            "manager": {"userId": "test-manager"},
            "colleagues": [{"userId": "test-colleague", "relationship": "colleague"}],
            "detail": {
                "jobTitle": "Mock title", "secondaryJobTitle": "Mock secondary title",
                "role": "Mock role", "secondaryRole": "Mock secondary role", "level": "Mock level",
                "layer": 0, "employeeId": "MOCK-001", "employeeType": "Employee",
                "startMonthYear": "2020-01-01", "endMonthYear": "2030-01-01",
                "description": "Mock position", "summary": "Mock summary",
                "company": {
                    "displayName": "Mock company", "companyCode": "MOCK",
                    "costCenter": "MOCK-CC", "division": "Mock division", "department": "Mock department",
                    "secondaryDepartment": "Mock secondary department", "officeLocation": "Mock office",
                    "pronunciation": "Mock company", "webUrl": "https://example.test",
                    "address": {
                        "street": "Mock street", "city": "Mock city", "state": "Mock state",
                        "postalCode": "00000", "postOfficeBox": "Mock box", "countryOrRegion": "US",
                    },
                },
            },
        }],
        "addresses": [], "anniversaries": [], "awards": [], "certifications": [],
        "educationalActivities": [], "emails": [], "interests": [], "languages": [],
        "notes": [], "patents": [], "phones": [], "projects": [], "publications": [],
        "skills": [], "webAccounts": [], "websites": [],
    }


def batch_response(request, *, make_profile=profile):
    """Graph JSON batch envelope: unique id/status/headers/body per subrequest.

    Source: https://learn.microsoft.com/en-us/graph/json-batching#processing-the-json-batch-response
    The POST envelope contains read-only GET requests; source data is schema-backed.
    """
    import json
    import httpx

    return httpx.Response(200, json={"responses": [
        {"id": row["id"], "status": 200, "body": make_profile()}
        for row in json.loads(request.content)["requests"]
    ]})
