from typing import List, Mapping, Any, Dict, Optional, Tuple

import vt
import pandas as pd
from enum import Enum
from vt_graph_api import VTGraph
from IPython.display import HTML, display

from typing import Dict, Set, List

class VTEntityType(Enum):
    """
    VTEntityType: Enum class for VirusTotal entity types
    """
    FILE = 'file'
    DOMAIN = 'domain'
    IP_ADDRESS = 'ip_address'
    URL = 'url'

class ColumnNames(Enum):
    ID = 'id'
    TYPE = 'type'
    DETECTIONS = 'detections'
    SCANS = 'scans'
    SOURCE = 'source'
    TARGET = 'target'
    RELATIONSHIP_TYPE = 'relationship_type'
    SOURCE_TYPE = 'source_type'
    TARGET_TYPE = 'target_type'

class VTObjectPorperties(Enum):
    ATTRIBUTES = 'attributes'
    RELATIONSHIPS = 'relationship'
    LAST_ANALYSIS_STATS = 'last_analysis_stats'
    MALICIOUS = 'malicious'

class VTLookupV3:
    """
    VTLookupV3: VirusTotal lookup of IoC reports.
    """

    _SUPPORTED_VT_TYPES: Set[VTEntityType] = {
        VTEntityType.FILE,
        VTEntityType.URL,
        VTEntityType.IP_ADDRESS,
        VTEntityType.DOMAIN
    }

    _MAPPING_TYPES_ENDPOINT: Dict[str, str] = {
        VTEntityType.FILE: "files",
        VTEntityType.URL: "urls",
        VTEntityType.IP_ADDRESS: "ip_addresses",
        VTEntityType.DOMAIN: "domains"
    }

    _BASIC_PROPERTIES_PER_TYPE: Dict[str, Set[str]] = {
        VTEntityType.FILE: {
            'type_description',
             'size',
             'first_submission_date',
             'last_submission_date',
             'times_submitted',
             'meaningful_name'},
        VTEntityType.URL: {'first_submission_date', 'last_submission_date', 'times_submitted'},
        VTEntityType.IP_ADDRESS: {'date', 'country', 'asn', 'as_owner'},
        VTEntityType.DOMAIN: {'id', 'creation_date', 'last_update_date', 'country'}
    }

    @property
    def supported_vt_types(self) -> List[str]:
        """
        Return list of VirusTotal supported IoC type names.

        Returns
        -------
        List[str]:
            List of VirusTotal supported IoC type names.
        """
        return self._SUPPORTED_VT_TYPES

    @classmethod
    def _get_endpoint_name(cls, vt_type: str) -> str:
        if VTEntityType(vt_type) not in cls._SUPPORTED_VT_TYPES:
            raise KeyError(f"Property type {vt_type} not supported")

        return cls._MAPPING_TYPES_ENDPOINT[VTEntityType(vt_type)]

    @classmethod
    def _parse_vt_object(cls, vt_object: vt.object.Object) -> pd.DataFrame:
        obj_dict = vt_object.to_dict()
        if VTObjectPorperties.ATTRIBUTES.value in obj_dict:
            attributes = obj_dict[VTObjectPorperties.ATTRIBUTES.value]
            vt_type = VTEntityType(vt_object.type)
            if vt_type not in cls._SUPPORTED_VT_TYPES:
                raise KeyError(f"Property type {vt_type} not supported")
            obj = {key: attributes[key] for key in cls._BASIC_PROPERTIES_PER_TYPE[vt_type] if key in attributes}
            df = pd.json_normalize(data=[obj])
            last_analysis_stats = attributes[VTObjectPorperties.LAST_ANALYSIS_STATS.value]
            df[ColumnNames.DETECTIONS.value] = last_analysis_stats[VTObjectPorperties.MALICIOUS.value]
            df[ColumnNames.SCANS.value] = sum(last_analysis_stats.values())
        else:
            df = pd.DataFrame()

        # Inject ID and Type columns
        df[ColumnNames.ID.value] = [vt_object.id]
        df[ColumnNames.TYPE.value] = [vt_object.type]
        return df.set_index([ColumnNames.ID.value])

    def __init__(self, vt_key: str):
        """
        Create a new instance of VTLookupV3 class.

        Parameters
        ----------
        vt_key: str
            VirusTotal API key
        """
        self._vt_key = vt_key
        self._vt_client = vt.Client(apikey=vt_key)

    def lookup_ioc(self, observable: str, vt_type: str) -> pd.DataFrame:
        """
        Look up and single IoC observable

        Parameters
        ----------
        observable: str
            The observable value
        vt_type: str
            The VT entity type
        
        Returns
        -------
            Attributes Pandas DataFrame with the properties of the entity

        Raises
        ------
        KeyError
            Unknown vt_type
        """

        if VTEntityType(vt_type) not in self.supported_vt_types:
            raise KeyError(f"Property type {vt_type} not supported")

        endpoint_name = self._get_endpoint_name(VTEntityType(vt_type))
        try:
            response: vt.object.Object = self._vt_client.get_object(f"/{endpoint_name}/{observable}")
            return self._parse_vt_object(response)
        except:
            raise Exception("It was not possible to get the data")
        finally:
            self._vt_client.close()

    def lookup_iocs(self,
                    observables_df: pd.DataFrame,
                    observable_column: str = ColumnNames.TARGET.value,
                    observable_type_column: str = ColumnNames.TARGET_TYPE.value
                    ):
        """
        Look up and multiple IoC observable

        Parameters
        ----------
        observables_df: pd.DataFrame
            A Pandas DataFrame, where each row is an observable
        observable_column:
            ID column of each observable
        observable_type_column:
            Type column of each observable.

        Returns
        -------
            Attributes Pandas DataFrame with the properties of the entities

        Raises
        ------
        KeyError
            Column not found in observables_df
        """

        _observables_df = observables_df.reset_index()

        for column in [observable_column, observable_type_column]:
            if column not in _observables_df.columns:
                raise KeyError(f"Column {column} not found in observables_df")

        observables_list = _observables_df[observable_column]
        types_list = _observables_df[observable_type_column]
        dfs = []
        for observable, observable_type in zip(observables_list, types_list):
            try:
                df = self.lookup_ioc(observable, observable_type)
                dfs.append(df)
            except:
                print(f"ERROR\t It was not possible to obtain results for {observable_type} {observable}")
                dfs.append(
                    pd.DataFrame(
                        data=[[observable, observable_type]],
                        columns=[ColumnNames.ID.value, ColumnNames.TYPE.value])
                    .set_index(ColumnNames.ID.value)
                )
        return pd.concat(dfs) if (len(dfs) > 0) else pd.DataFrame()

    def lookup_ioc_relationships(self,
                                 observable: str,
                                 vt_type: str,
                                 relationship: str,
                                 limit: int = None) -> pd.DataFrame:
        """
        Look up and single IoC observable relationships

        Parameters
        ----------
        observable: str
            The observable value
        vt_type: str
            The VT entity type
        relationship: str
            Desired relationship
        limit: int
            Relations limit
        
        Returns
        -------
            Relationship Pandas DataFrame with the relationships of the entity

        Raises
        ------
        KeyError
            Unknown vt_type
        """
        if VTEntityType(vt_type) not in self.supported_vt_types:
            raise KeyError(f"Property type {vt_type} not supported")

        endpoint_name = self._get_endpoint_name(vt_type)

        if limit is None:
            endpoint_name = self._get_endpoint_name(VTEntityType(vt_type))
            try:
                response: vt.object.Object = self._vt_client.get_object(
                    f"/{endpoint_name}/{observable}?relationship_counters=true")
                relationships = response.relationships
                limit: int = relationships[relationship]['meta']["count"] if relationship in relationships else 0
            except:
                print(f"ERROR: Could not obtain relationship limit for {vt_type} {observable}")
                return pd.DataFrame()

        if limit == 0 or limit is None:
            return pd.DataFrame()

        try:
            # print(f"Obtaining {limit} relationships for {vt_type} {observable}")
            response: vt.Iterator = self._vt_client.iterator(
                f"/{endpoint_name}/{observable}/relationships/{relationship}",
                batch_size=40,
                limit=limit)
            objects = [self._parse_vt_object(r) for r in response]
            df = pd.concat(objects) if len(objects) > 0 else pd.DataFrame()

            if(len(objects) > 0):
                # Inject source and target columns
                df[ColumnNames.SOURCE.value] = observable
                df[ColumnNames.SOURCE_TYPE.value] = VTEntityType(vt_type).value
                df[ColumnNames.RELATIONSHIP_TYPE.value] = relationship
                df.reset_index(inplace=True)
                df.rename(columns={
                    ColumnNames.ID.value: ColumnNames.TARGET.value,
                    ColumnNames.TYPE.value: ColumnNames.TARGET_TYPE.value
                }, inplace=True)
                df.set_index([ColumnNames.SOURCE.value, ColumnNames.TARGET.value], inplace=True)
        except:
            raise Exception("It was not possible to get the data")
        finally:
            self._vt_client.close()

        return df

    def lookup_iocs_relationships(self,
                                 observables_df: pd.DataFrame,
                                 relationship: str,
                                 observable_column: str = ColumnNames.TARGET.value,
                                 observable_type_column: str = ColumnNames.TARGET_TYPE.value,
                                 limit: int = None
                                 ) -> pd.DataFrame:
        """
         Look up and single IoC observable relationships

         Parameters
         ----------
         observables_df: pd.DataFrame
            A Pandas DataFrame, where each row is an observable
        relationship: str
            Desired relationship
        observable_column:
            ID column of each observable
        observable_type_column:
            Type column of each observable.
        limit: int
            Relations limit

         Returns
         -------
             Relationship Pandas DataFrame with the relationships of each observable.

         Raises
         ------
         KeyError
             Column not found in observables_df
         """

        _observables_df = observables_df.reset_index()

        for column in [observable_column, observable_type_column]:
            if column not in _observables_df.columns:
                raise KeyError(f"Column {column} not found in observables df")

        observables_list = _observables_df[observable_column]
        types_list = _observables_df[observable_type_column]
        dfs = []

        for observable, observable_type in zip(observables_list, types_list):
            try:
                df = self.lookup_ioc_relationships(observable, observable_type, relationship, limit)
                dfs.append(df)
            except:
                print(f"ERROR:\t It was not possible to get the data for {observable_type} {observable}")
                dfs.append(
                    pd.DataFrame(
                        data=[[observable, observable_type]],
                        columns=[ColumnNames.ID.value, ColumnNames.TYPE.value])
                    .set_index(ColumnNames.ID.value)
                )

        return pd.concat(dfs) if len(dfs) > 0 else pd.DataFrame()

    def create_vt_graph(self,
                        relationship_dfs: List[pd.DataFrame],
                        name: str,
                        private: bool = True) -> str:
        """
        Creates a VirusTotal Graph with a set of Relationship DataFrames.

        Parameters
        ----------
        relationship_dfs:
            List of Relationship DataFrames
        name:
            New graph name
        private
            Indicates if the Graph is private or not.

        Returns
        -------
            Graph ID

        Raises
            ValueError when there are no relationship DataFrames
        """
        if len(relationship_dfs) == 0:
            raise ValueError("There are no relationship DataFrames")

        concatenated_df = pd.concat(relationship_dfs).reset_index()

        # Create nodes DF, with source and target
        sources_df = concatenated_df \
            .groupby(ColumnNames.SOURCE.value)[ColumnNames.SOURCE_TYPE.value] \
            .first() \
            .reset_index() \
            .rename(columns={
                ColumnNames.SOURCE.value: ColumnNames.ID.value,
                ColumnNames.SOURCE_TYPE.value: ColumnNames.TYPE.value
            })

        target_df = concatenated_df \
            .groupby(ColumnNames.TARGET.value)[ColumnNames.TARGET_TYPE.value] \
            .first() \
            .reset_index() \
            .rename(columns={
                ColumnNames.TARGET.value: ColumnNames.ID.value,
                ColumnNames.TARGET_TYPE.value: ColumnNames.TYPE.value
            })

        nodes_df = pd.concat([sources_df, target_df])

        graph = VTGraph(self._vt_key, name=name, private=private)

        for _, row in nodes_df.iterrows():
            graph.add_node(node_id=row[ColumnNames.ID.value], node_type=row[ColumnNames.TYPE.value])

        for _, row in concatenated_df.iterrows():
            graph.add_link(
                source_node=row[ColumnNames.SOURCE.value],
                target_node=row[ColumnNames.TARGET.value],
                connection_type=row[ColumnNames.RELATIONSHIP_TYPE.value]
            )
        graph.save_graph()

        return graph.graph_id

    def render_vt_graph(self, graph_id: str, width: int = 800, height: int = 600):
        """
        Displays a VTGraph in a Jupyter Notebook

        Parameters
        ----------
        graph_id:
            Graph ID
        width
            Graph width.
        height
            Graph height
        """
        display(HTML(
            f'''
              <iframe
                src="https://www.virustotal.com/graph/embed/{graph_id}"
                width="{width}"
                height="{height}">
              </iframe>
                
            '''
        ))