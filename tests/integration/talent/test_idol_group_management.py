import io
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.models.talent import Group, Idol
from main import app

# ───────────────────────────────────────────────────────────────
# Idol and group writes over real HTTP + Postgres: company scoping for managers, reference
# validation (group in another company, deactivated group, unknown color), soft delete /
# reactivate, and the public reads that should hide inactive rows. Role gates alone are covered in
# test_idols.py / test_groups.py. Rows created through the API are removed by the seeded
# company's ON DELETE CASCADE.
# ───────────────────────────────────────────────────────────────

client = TestClient(app)
PNG = ("face.png", io.BytesIO(b"\x89PNG fake"), "image/png")


@pytest.fixture(autouse=True)
def local_storage(tmp_path):
    from app.utils import storage

    with patch.object(storage.settings, "LOCAL_UPLOAD_DIR", str(tmp_path)):
        with patch.object(storage, "_backend", storage.LocalStorageBackend()):
            yield tmp_path


@pytest.fixture
def talent(seed):
    company_a, company_b = seed.company(), seed.company()
    return {
        "seed": seed,
        "company_a": company_a, "company_b": company_b,
        "group_a": seed.group(company_a.id),
        "group_b": seed.group(company_b.id),
        "manager_a": seed.user("manager", company_a.id),
        "admin": seed.user("admin"),
    }


def h(talent, who="manager_a"):
    return talent["seed"].headers(talent[who])


def reload(talent, model, id_):
    talent["seed"].db.expire_all()
    return talent["seed"].db.get(model, id_)


# ───────────────────────────────────────────────────────────────
# Idols
# ───────────────────────────────────────────────────────────────

def add_idol(talent, who="manager_a", files=None, **fields):
    form = {"name": f"idol-{uuid.uuid4()}", "company_id": str(talent["company_a"].id)}
    form.update({k: str(v) for k, v in fields.items()})
    return client.post("/idols/add", data=form, files=files, headers=h(talent, who))


def test_manager_adds_idol_to_own_group_with_image(talent):
    color = talent["seed"].color()
    res = add_idol(talent, files={"image": PNG}, group_id=talent["group_a"].id, color_id=color.id,
                   date_of_birth="2001-02-03", hometown="Osaka")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["group_id"] == str(talent["group_a"].id)
    assert body["color_id"] == str(color.id)
    assert body["profile_image_url"].startswith("/uploads/idols/")


def test_manager_cannot_add_idol_to_other_company(talent):
    assert add_idol(talent, company_id=talent["company_b"].id).status_code == 403


def test_add_idol_rejects_group_from_other_company(talent):
    assert add_idol(talent, who="admin", group_id=talent["group_b"].id).status_code == 400


def test_add_idol_rejects_deactivated_group(talent):
    inactive = talent["seed"].group(talent["company_a"].id, is_active=False)
    assert add_idol(talent, group_id=inactive.id).status_code == 400


@pytest.mark.parametrize("field", ["group_id", "color_id"])
def test_add_idol_unknown_reference_404(talent, field):
    assert add_idol(talent, **{field: uuid.uuid4()}).status_code == 404


def test_add_idol_bad_image_400(talent):
    files = {"image": ("x.html", io.BytesIO(b"<p>"), "text/html")}
    assert add_idol(talent, files=files).status_code == 400


def idol_update(idol, **overrides):
    payload = {"name": idol.name, "group_id": str(idol.group_id) if idol.group_id else None}
    payload.update(overrides)
    return payload


def test_update_idol_moves_group_within_company(talent):
    seed = talent["seed"]
    idol = seed.idol(talent["company_a"].id)
    other_group = seed.group(talent["company_a"].id)

    res = client.put(f"/idols/update/{idol.id}", json=idol_update(idol, name="Renamed", group_id=str(other_group.id)),
                     headers=h(talent))
    assert res.status_code == 200
    assert (res.json()["name"], res.json()["group_id"]) == ("Renamed", str(other_group.id))


def test_update_idol_may_stay_in_group_that_was_deactivated(talent):
    seed = talent["seed"]
    group = seed.group(talent["company_a"].id)
    idol = seed.idol(talent["company_a"].id, group_id=group.id)
    group.is_active = False
    seed.db.commit()

    res = client.put(f"/idols/update/{idol.id}", json=idol_update(idol, hometown="Kyoto"), headers=h(talent))
    assert res.status_code == 200


def test_update_idol_cannot_move_into_deactivated_group(talent):
    seed = talent["seed"]
    idol = seed.idol(talent["company_a"].id)
    inactive = seed.group(talent["company_a"].id, is_active=False)

    res = client.put(f"/idols/update/{idol.id}", json=idol_update(idol, group_id=str(inactive.id)), headers=h(talent))
    assert res.status_code == 400


@pytest.mark.parametrize(
    ("overrides", "status"),
    [({"group_id": "group_b"}, 400), ({"color_id": "random"}, 404)],
)
def test_update_idol_reference_errors(talent, overrides, status):
    idol = talent["seed"].idol(talent["company_a"].id)
    resolved = {k: str(talent["group_b"].id) if v == "group_b" else str(uuid.uuid4()) for k, v in overrides.items()}
    res = client.put(f"/idols/update/{idol.id}", json=idol_update(idol, **resolved), headers=h(talent, "admin"))
    assert res.status_code == status


@pytest.mark.parametrize(
    ("method", "path"),
    [("put", "/idols/update/{id}"), ("delete", "/idols/delete/{id}"), ("patch", "/idols/activate/{id}")],
)
def test_idol_writes_scoped_and_404(talent, method, path):
    other_idol = talent["seed"].idol(talent["company_b"].id)
    kwargs = {"json": idol_update(other_idol)} if method == "put" else {}

    forbidden = getattr(client, method)(path.format(id=other_idol.id), headers=h(talent), **kwargs)
    missing = getattr(client, method)(path.format(id=uuid.uuid4()), headers=h(talent, "admin"), **kwargs)
    assert (forbidden.status_code, missing.status_code) == (403, 404)


def test_idol_soft_delete_hides_from_public_reads_then_reactivate(talent):
    idol = talent["seed"].idol(talent["company_a"].id, group_id=talent["group_a"].id)

    assert client.get(f"/idols/{idol.id}/detail").status_code == 200
    assert client.delete(f"/idols/delete/{idol.id}", headers=h(talent)).status_code == 200
    assert reload(talent, Idol, idol.id).is_active is False
    assert client.get(f"/idols/{idol.id}/detail").status_code == 404

    res = client.patch(f"/idols/activate/{idol.id}", headers=h(talent))
    assert res.status_code == 200 and res.json()["is_active"] is True
    assert client.get(f"/idols/{idol.id}/detail").status_code == 200


def test_idol_image_replace_scoped(talent):
    own = talent["seed"].idol(talent["company_a"].id)
    other = talent["seed"].idol(talent["company_b"].id)

    res = client.post(f"/idols/{own.id}/image", files={"image": PNG}, headers=h(talent))
    assert res.status_code == 200 and res.json()["profile_image_url"].endswith(".png")
    assert client.post(f"/idols/{other.id}/image", files={"image": PNG}, headers=h(talent)).status_code == 403
    assert client.post(f"/idols/{uuid.uuid4()}/image", files={"image": PNG}, headers=h(talent, "admin")).status_code == 404
    bad = {"image": ("x.txt", io.BytesIO(b"x"), "text/plain")}
    assert client.post(f"/idols/{own.id}/image", files=bad, headers=h(talent)).status_code == 400


def test_idol_public_reads(talent):
    idol = talent["seed"].idol(talent["company_a"].id, group_id=talent["group_a"].id)

    assert client.get(f"/idols/{idol.id}").json()["name"] == idol.name
    assert str(idol.id) in {i["id"] for i in client.get("/idols/all").json()}
    members = client.get("/idols/members-page").json()
    assert str(idol.id) in {i["id"] for i in members["idols"]}
    assert str(talent["group_a"].id) in {g["id"] for g in members["groups"]}
    detail = client.get(f"/idols/{idol.id}/detail").json()
    assert (detail["idol"]["id"], detail["group"]["id"]) == (str(idol.id), str(talent["group_a"].id))


# ───────────────────────────────────────────────────────────────
# Groups
# ───────────────────────────────────────────────────────────────

def test_manager_adds_group_for_own_company_only(talent):
    own = client.post("/groups/add", json={"name": "New Unit", "company_id": str(talent["company_a"].id)}, headers=h(talent))
    other = client.post("/groups/add", json={"name": "Nope", "company_id": str(talent["company_b"].id)}, headers=h(talent))

    assert own.status_code == 200 and own.json()["company_id"] == str(talent["company_a"].id)
    assert other.status_code == 403


def test_add_group_unknown_company_404(talent):
    res = client.post("/groups/add", json={"name": "Ghost", "company_id": str(uuid.uuid4())}, headers=h(talent, "admin"))
    assert res.status_code == 404


def test_update_group(talent):
    res = client.put(f"/groups/update/{talent['group_a'].id}",
                     json={"name": "Renamed", "debut_date": "2020-05-05", "description": "d"}, headers=h(talent))
    assert res.status_code == 200
    assert (res.json()["name"], res.json()["debut_date"]) == ("Renamed", "2020-05-05")


@pytest.mark.parametrize(
    ("method", "path"),
    [("put", "/groups/update/{id}"), ("delete", "/groups/delete/{id}"), ("patch", "/groups/activate/{id}")],
)
def test_group_writes_scoped_and_404(talent, method, path):
    kwargs = {"json": {"name": "x"}} if method == "put" else {}
    forbidden = getattr(client, method)(path.format(id=talent["group_b"].id), headers=h(talent), **kwargs)
    missing = getattr(client, method)(path.format(id=uuid.uuid4()), headers=h(talent, "admin"), **kwargs)
    assert (forbidden.status_code, missing.status_code) == (403, 404)


def test_group_soft_delete_then_reactivate(talent):
    group_id = talent["group_a"].id
    assert client.get(f"/groups/{group_id}/detail").status_code == 200

    assert client.delete(f"/groups/delete/{group_id}", headers=h(talent)).status_code == 200
    assert reload(talent, Group, group_id).is_active is False
    assert str(group_id) not in {g["id"] for g in client.get("/groups/all").json()}

    res = client.patch(f"/groups/activate/{group_id}", headers=h(talent))
    assert res.status_code == 200 and res.json()["is_active"] is True


def test_group_public_reads(talent):
    group = talent["group_a"]
    member = talent["seed"].idol(talent["company_a"].id, group_id=group.id)

    assert client.get(f"/groups/{group.id}").json()["name"] == group.name
    page = {g["id"]: g for g in client.get("/groups/groups-page").json()["groups"]}
    assert page[str(group.id)]["member_count"] == 1
    assert str(group.id) in {g["id"] for g in client.get("/groups/manager-groups-page", headers=h(talent)).json()["groups"]}
    detail = client.get(f"/groups/{group.id}/detail").json()
    assert [m["id"] for m in detail["members"]] == [str(member.id)]


# ───────────────────────────────────────────────────────────────
# Manager settings pages: a manager sees only their own company; an admin sees every company
# ───────────────────────────────────────────────────────────────

def test_manager_talent_pages_scoped_to_own_company(talent):
    seed = talent["seed"]
    idol_a = seed.idol(talent["company_a"].id, group_id=talent["group_a"].id)
    idol_b = seed.idol(talent["company_b"].id, group_id=talent["group_b"].id)
    ours = {str(idol_a.id), str(idol_b.id), str(talent["group_a"].id), str(talent["group_b"].id)}

    def ids(path, key, who):
        res = client.get(path, headers=h(talent, who))
        assert res.status_code == 200
        return {row["id"] for row in res.json()[key]} & ours

    for who, idols, groups in [
        ("manager_a", {str(idol_a.id)}, {str(talent["group_a"].id)}),
        ("admin", {str(idol_a.id), str(idol_b.id)}, {str(talent["group_a"].id), str(talent["group_b"].id)}),
    ]:
        assert ids("/idols/manager-idols-page", "idols", who) == idols
        assert ids("/idols/manager-idols-page", "groups", who) == groups
        assert ids("/idols/manager-idol-form-page", "idols", who) == idols
        assert ids("/idols/manager-idol-form-page", "groups", who) == groups
        assert ids("/groups/manager-groups-page", "groups", who) == groups


def test_manager_idol_form_page_keeps_shared_colors(talent):
    color = talent["seed"].color()
    body = client.get("/idols/manager-idol-form-page", headers=h(talent)).json()
    assert str(color.id) in {c["id"] for c in body["colors"]}
