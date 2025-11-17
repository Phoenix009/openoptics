from openoptics.backend.backend_base import Backend
from pprint import pprint
print = pprint

try:
    from ns import ns
    ns.LogComponentEnable("UdpEchoClientApplication", ns.LOG_LEVEL_INFO);
    ns.LogComponentEnable("UdpEchoServerApplication", ns.LOG_LEVEL_INFO);

except ModuleNotFoundError:
    raise SystemExit(
        "Error: ns3 Python module not found;"
        " Python bindings may not be enabled"
        " or your PYTHONPATH might not be properly configured"
    )

class BackendNs3(Backend):

    def __init__(self):
        self.nodeid_to_ocs_port = {}
        self.ocs_ports = ns.NetDeviceContainer()
        self.tor_ports = ns.NetDeviceContainer()
        self.ocs = None
        self.tors = None

    def create_nodes(self, nb_node):
        """
        Add OCS and Nodes to ns3 topology.

        Creates the ns3 topology with OCS switch and ToR switches,
        establishes connections between them.
        To-do: Move backend-related code to a seperate class/file
        """

        self.tors = ns.NodeContainer()
        self.tors.Create(nb_node)

        ocs_switch = ns.NodeContainer()
        ocs_switch.Create(1)

        self.ocs = ocs_switch.Get(0)

        csma = ns.CsmaHelper()

        # todo: Do we want to set this to some cmd args?
        csma.SetChannelAttribute("DataRate", ns.DataRateValue(ns.DataRate(5000000)))
        csma.SetChannelAttribute("Delay", ns.TimeValue(ns.MilliSeconds(2)))


        for node_id in range(nb_node):
            link = csma.Install(ns.NodeContainer(ns.NodeContainer(self.tors.Get(node_id)), ocs_switch))
            tor_port = link.Get(0)
            ocs_port = link.Get(1)
            self.ocs_ports.Add(ocs_port)
            self.tor_ports.Add(tor_port)
            self.nodeid_to_ocs_port[node_id] = ocs_port

    def cal_node_port_to_ocs_port(self, node_id, port_id):
        return self.nodeid_to_ocs_port.get(node_id)

    def setup_ocs(self, ocs_slice_port1_port2, nb_time_slices, time_slice_duration_ms):
        ocs_helper = ns.OCSHelper()
        ocs_helper.SetDeviceAttribute("TimeSliceCount", ns.UintegerValue(nb_time_slices))
        ocs_helper.SetDeviceAttribute("TimeSliceDuration", ns.TimeValue(ns.MilliSeconds(time_slice_duration_ms)))

        schedule = ns.OCSSchedule()


        for (ts, ocs_port1, ocs_port2) in ocs_slice_port1_port2:

            ocs_port1_mac = ns.Mac48Address.ConvertFrom(ocs_port1.GetAddress())
            ocs_port2_mac = ns.Mac48Address.ConvertFrom(ocs_port2.GetAddress())

            schedule.insert(((ts, ocs_port1_mac), ocs_port2))
            schedule.insert(((ts, ocs_port2_mac), ocs_port1))

        ocs_helper.Install(self.ocs, self.ocs_ports, schedule)
    
    def start(self):
        ns.Simulator.Run()
        ns.Simulator.Destroy()