from moonkvsim.store.eviction import FIFOEvictionStrategy, LRUEvictionStrategy


def test_lru_add_update_and_evict_match_pinned_order() -> None:
    policy = LRUEvictionStrategy()
    policy.add_key("a")
    policy.add_key("b")
    policy.add_key("c")
    policy.update_key("a")

    assert policy.keys_mru_to_lru == ("a", "c", "b")
    assert policy.keys_lru_to_mru == ("b", "c", "a")
    assert policy.evict_key() == "b"
    policy.audit()


def test_lru_readding_key_does_not_duplicate_index() -> None:
    policy = LRUEvictionStrategy()
    policy.add_key("a")
    policy.add_key("b")
    policy.add_key("a")

    assert policy.keys_mru_to_lru == ("a", "b")
    assert len(policy) == 2
    assert policy.remove_key("missing") is False
    assert policy.remove_key("a") is True
    policy.audit()


def test_fifo_update_is_noop_and_duplicate_adds_remain_distinct() -> None:
    policy = FIFOEvictionStrategy()
    policy.add_key("a")
    policy.add_key("b")
    policy.add_key("a")
    policy.update_key("a")
    assert policy.remove_key("a") is False

    assert [policy.evict_key(), policy.evict_key(), policy.evict_key()] == [
        "a",
        "b",
        "a",
    ]
    assert policy.evict_key() is None
