"""SyncFlow Factory for creating SyncFlows based on resource types"""
import logging
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

import boto3
from botocore.config import Config

from samcli.lib.providers.provider import Stack, get_resource_by_id, ResourceIdentifier
from samcli.lib.providers.sam_base_provider import SamBaseProvider
from samcli.lib.providers.sam_api_provider import SamApiProvider
from samcli.lib.providers.cfn_api_provider import CfnApiProvider
from samcli.lib.utils.packagetype import ZIP, IMAGE

from samcli.lib.sync.sync_flow import SyncFlow
from samcli.lib.sync.flows.function_sync_flow import FunctionSyncFlow
from samcli.lib.sync.flows.zip_function_sync_flow import ZipFunctionSyncFlow
from samcli.lib.sync.flows.image_function_sync_flow import ImageFunctionSyncFlow

if TYPE_CHECKING:
    from samcli.commands.deploy.deploy_context import DeployContext
    from samcli.commands.build.build_context import BuildContext

LOG = logging.getLogger(__name__)


class SyncFlowFactory:
    """Factory class for SyncFlow
    Creates appropriate SyncFlow types based on stack resource types
    """

    _deploy_context: "DeployContext"
    _build_context: "BuildContext"
    _stacks: List[Stack]
    _boto_config: Config
    _physical_id_mapping: Dict[str, str]

    def __init__(self, build_context: "BuildContext", deploy_context: "DeployContext", stacks: List[Stack]) -> None:
        """
        Parameters
        ----------
        build_context : BuildContext
            BuildContext to be passed into each individual SyncFlow
        deploy_context : DeployContext
            DeployContext to be passed into each individual SyncFlow
        stacks : List[Stack]
            List of stacks containing a root stack and optional nested ones
        """
        self._deploy_context = deploy_context
        self._build_context = build_context
        self._stacks = stacks

        self._boto_config = Config(region_name=self._deploy_context.region if self._deploy_context.region else None)

        self._physical_id_mapping = dict()

    def load_physical_id_mapping(self) -> None:
        """Load physical IDs of the stack resources from remote"""
        LOG.debug("Loading physical ID mapping")
        self._physical_id_mapping.clear()
        stack = boto3.resource("cloudformation", config=self._boto_config).Stack(self._deploy_context.stack_name)
        resources = stack.resource_summaries.all()
        for resource in resources:
            self._physical_id_mapping[resource.logical_resource_id] = resource.physical_resource_id

    def _create_lambda_flow(self, resource_identifier: str, resource: Dict[str, Any]) -> Optional[FunctionSyncFlow]:
        package_type = resource.get("Properties", dict()).get("PackageType", ZIP)
        if package_type == ZIP:
            return ZipFunctionSyncFlow(
                resource_identifier,
                self._build_context,
                self._deploy_context,
                self._physical_id_mapping,
                self._stacks,
            )
        if package_type == IMAGE:
            return ImageFunctionSyncFlow(
                resource_identifier,
                self._build_context,
                self._deploy_context,
                self._physical_id_mapping,
                self._stacks,
            )
        return None

    def _create_layer_flow(self, resource_identifier: str, resource: Dict[str, str]) -> SyncFlow:
        pass

    def _create_rest_api_flow(self, resource_identifier: str, resource: Dict[str, str]) -> SyncFlow:
        pass

    def _create_api_flow(self, resource_identifier: str, resource: Dict[str, str]) -> SyncFlow:
        pass

    # SyncFlow mapping between resource type and creation function
    FLOW_FACTORY_FUNCTIONS: Dict[str, Callable[..., Optional[SyncFlow]]] = {
        SamBaseProvider.LAMBDA_FUNCTION: _create_lambda_flow,
        SamBaseProvider.SERVERLESS_FUNCTION: _create_lambda_flow,
        SamBaseProvider.SERVERLESS_LAYER: _create_layer_flow,
        SamBaseProvider.LAMBDA_LAYER: _create_layer_flow,
        SamApiProvider.SERVERLESS_API: _create_rest_api_flow,
        CfnApiProvider.APIGATEWAY_RESTAPI: _create_rest_api_flow,
        SamApiProvider.SERVERLESS_HTTP_API: _create_api_flow,
        CfnApiProvider.APIGATEWAY_V2_API: _create_api_flow,
    }

    def create_sync_flow(self, resource_identifier: ResourceIdentifier) -> Optional[SyncFlow]:
        """Create an appropriate SyncFlow type based on stack resource type

        Parameters
        ----------
        resource_identifier : ResourceIdentifier
            Resource identifier of the resource

        Returns
        -------
        Optional[SyncFlow]
            SyncFlow for the resource. Returns None if resource cannot be found or have no associating SyncFlow type.
        """
        resource = get_resource_by_id(self._stacks, resource_identifier)
        if not resource:
            return None

        resource_type = resource.get("Type")
        if not resource_type:
            return None

        LOG.debug("Creating SyncFlow for %s", resource_type)
        factory_function = SyncFlowFactory.FLOW_FACTORY_FUNCTIONS.get(resource_type, None)
        return factory_function(self, str(resource_identifier), resource) if factory_function else None
