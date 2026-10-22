from sqlalchemy import select


def test_demo_seed_is_consistent_and_idempotent(db, admin):
    from almlight.modules.projects.models import Project
    from almlight.seed.demo import seed_demo

    seed_demo(db)
    seed_demo(db)  # second run is a no-op
    assert db.execute(select(Project.key)).scalars().all() == ["DEMO"]
    stats = admin.get("/projects/DEMO/stats")
    assert stats["total_items"] > 50 and stats["open_changes"] == 1
    model = admin.get("/projects/DEMO/variants/feature-model")
    assert all(v["errors"] == [] for v in model["variants"]) and model["unknown_codes"] == []
    cov = admin.get("/projects/DEMO/coverage?type=system_requirement")
    assert cov["total"] == 7 and cov["allocated_pct"] == 100
    assert admin.get("/admin/audit/verify")["ok"] is True
    assert len(admin.get("/projects/DEMO/baselines")) == 1
    hart = admin.get("/projects/DEMO/variants/VAR-2/resolve")
    titles = {i["title"] for i in hart["included"]}
    assert "Provide HART communication" in titles and "Provide an IO-Link interface" not in titles
