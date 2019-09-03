# coding=utf-8
# --------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
#
# Code generated by Microsoft (R) AutoRest Code Generator.
# Changes may cause incorrect behavior and will be lost if the code is
# regenerated.
# --------------------------------------------------------------------------

from .ssis_object_metadata import SsisObjectMetadata


class SsisEnvironment(SsisObjectMetadata):
    """Ssis environment.

    All required parameters must be populated in order to send to Azure.

    :param id: Metadata id.
    :type id: long
    :param name: Metadata name.
    :type name: str
    :param description: Metadata description.
    :type description: str
    :param type: Required. Constant filled by server.
    :type type: str
    :param folder_id: Folder id which contains environment.
    :type folder_id: long
    :param variables: Variable in environment
    :type variables: list[~azure.mgmt.datafactory.models.SsisVariable]
    """

    _validation = {
        'type': {'required': True},
    }

    _attribute_map = {
        'id': {'key': 'id', 'type': 'long'},
        'name': {'key': 'name', 'type': 'str'},
        'description': {'key': 'description', 'type': 'str'},
        'type': {'key': 'type', 'type': 'str'},
        'folder_id': {'key': 'folderId', 'type': 'long'},
        'variables': {'key': 'variables', 'type': '[SsisVariable]'},
    }

    def __init__(self, **kwargs):
        super(SsisEnvironment, self).__init__(**kwargs)
        self.folder_id = kwargs.get('folder_id', None)
        self.variables = kwargs.get('variables', None)
        self.type = 'Environment'