
import abc

class Backend(abc.ABC):
    @abc.abstractmethod
    def create_nodes(
        self, 
        nb_node,
        nb_link,
        nb_host_per_tor,
        nb_time_slices,
        time_slice_duration_ms,
        arch_mode
        ):
        pass

    @abc.abstractmethod
    def cal_node_port_to_ocs_port(self, node_id, port_id):
        pass

    @abc.abstractmethod
    def setup_ocs(self, ocs_slice_port1_port2, nb_time_slices, time_slice_duration_ms):
        pass

    @abc.abstractmethod
    def add_time_flow_entry(
        self, 
        node_id, 
        entries, # Union[List[TimeFlowEntry],TimeFlowEntry], 
        routing_mode="Per-hop"
    ):
        pass

    @abc.abstractmethod
    def start(self):
        pass
