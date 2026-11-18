"""Router places the peer outside the execution host and accounts for H2D load."""

from moonkvsim.aegiskv.current.router import Router


def test_peer_is_off_host_and_prefers_a_quiet_link():
    hosts = (0, 1, 1)
    load = {0: 0, 1: 0, 2: 0}
    free = {0: 100, 1: 100, 2: 100}
    flows = {0: 0, 1: 3, 2: 0}
    router = Router(
        hosts,
        queue_load=lambda worker: load[worker],
        free_dram=lambda worker: free[worker],
        h2d_flows=lambda worker: flows[worker],
        has_prefix=lambda worker: False,
    )
    assert router.choose_peer(0, [0, 1, 2]) == 2
    flows[2] = 9
    assert router.choose_peer(0, [0, 1, 2]) == 1
    load[0] = 4
    assert router.place_execution([0, 1, 2]) == 1


if __name__ == "__main__":
    test_peer_is_off_host_and_prefers_a_quiet_link()
    print("ok")
