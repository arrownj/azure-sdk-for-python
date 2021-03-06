# ------------------------------------
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
# ------------------------------------
import itertools
import os

from azure.identity import CredentialUnavailableError
from azure.identity.aio import EnvironmentCredential
from azure.identity._constants import EnvironmentVariables
import pytest

from helpers import mock
from test_environment_credential import ALL_VARIABLES


@pytest.mark.asyncio
async def test_incomplete_configuration():
    """get_token should raise CredentialUnavailableError for incomplete configuration."""

    with mock.patch.dict(os.environ, {}, clear=True):
        with pytest.raises(CredentialUnavailableError) as ex:
            await EnvironmentCredential().get_token("scope")

    for a, b in itertools.combinations(ALL_VARIABLES, 2):  # all credentials require at least 3 variables set
        with mock.patch.dict(os.environ, {a: "a", b: "b"}, clear=True):
            with pytest.raises(CredentialUnavailableError) as ex:
                await EnvironmentCredential().get_token("scope")


@pytest.mark.parametrize(
    "credential_name,environment_variables",
    (
        ("ClientSecretCredential", EnvironmentVariables.CLIENT_SECRET_VARS),
        ("CertificateCredential", EnvironmentVariables.CERT_VARS),
    ),
)
def test_passes_authority_argument(credential_name, environment_variables):
    """the credential pass the 'authority' keyword argument to its inner credential"""

    authority = "authority"

    with mock.patch.dict("os.environ", {variable: "foo" for variable in environment_variables}, clear=True):
        with mock.patch(EnvironmentCredential.__module__ + "." + credential_name) as mock_credential:
            EnvironmentCredential(authority=authority)

    assert mock_credential.call_count == 1
    _, kwargs = mock_credential.call_args
    assert kwargs["authority"] == authority
