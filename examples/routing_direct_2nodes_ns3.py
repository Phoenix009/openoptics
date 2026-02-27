import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openoptics import Toolbox, OpticalTopo, OpticalRouting

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

if __name__ == "__main__":
    net = Toolbox.BaseNetwork(
        name="my_network",
        backend="ns3",
        nb_node=8,
        time_slice_duration_ms=200,  # in ms
        use_webserver=True,
    )

    circuits = OpticalTopo.round_robin(nb_node=8)
    # print(circuits)
    assert net.deploy_topo(circuits)

    paths = OpticalRouting.find_direct_path(net.get_topo(), node1=0, node2=1)
    paths.extend(OpticalRouting.find_direct_path(net.get_topo(), node1=1, node2=0))
    net.deploy_routing(paths, routing_mode="Per-hop")

    # ------------ setup echo client and server ------------
    echoServerNode = net.backend.hosts.Get(0)
    echoServerAddress = net.backend.host_ip_interfaces.GetAddress(0)

    echoClientNode = net.backend.hosts.Get(1)
    echoClientAddress = net.backend.host_ip_interfaces.GetAddress(1)

    net.setup_echo_server_client(
        echoServerNode, echoServerAddress,
        echoClientNode, echoClientAddress
    )

    net.start()
