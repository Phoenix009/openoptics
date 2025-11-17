
import abc

class Backend(abc.ABC):
    @abc.abstractmethod
    def create_nodes(self, nb_node):
        pass

    @abc.abstractmethod
    def cal_node_port_to_ocs_port(self, node_id, port_id):
        pass

    @abc.abstractmethod
    def setup_ocs(self, ocs_slice_port1_port2, nb_time_slices, time_slice_duration_ms):
        pass

    @abc.abstractmethod
    def start(self):
        pass
