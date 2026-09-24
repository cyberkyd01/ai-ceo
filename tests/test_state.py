from ai_ceo.state import CompanyStore


def test_kv_metrics_and_actions(tmp_path):
    s = CompanyStore(tmp_path / "c")
    s.put("dossier", {"name": "x"})
    assert s.get("dossier") == {"name": "x"}
    assert s.age_days("dossier") < 1 and s.age_days("missing") == float("inf")
    s.record_metric("stars", 1); s.record_metric("stars", 5)
    assert s.latest_metrics() == {"stars": 5.0}
    assert [v for _, v in s.metric_history("stars")] == [1.0, 5.0]
    cid = s.start_cycle()
    aid = s.add_action(None, cid, "manual", "t", "internal", "marketing", {"a": "b"}, 0, "queued")
    s.set_action(aid, "done", "ok")
    assert s.action(aid)["status"] == "done"
    s.update_payload(aid, {"a": "c"})
    assert '"c"' in s.action(aid)["payload"]
    s.record_usage(cid, [{"label": "l", "model": "m", "in": 1, "out": 1, "usd": 0.5}])
    assert s.spend_this_month_usd() == 0.5
