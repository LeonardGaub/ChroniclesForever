import copy

import pytest

from forever_chronicle.domain import event_types, stats
from forever_chronicle.importing.sv_importer import SavedVariablesImporter
from forever_chronicle.storage.repository import Recipe, RecipeCategory, Repository
from forever_chronicle.wow.lua_parser import parse_saved_variables

GUID = "Player-4619-0112A417"


@pytest.fixture
def data(addon_fixture):
    return parse_saved_variables(addon_fixture.read_text(encoding="utf-8"))


def professions_of(data):
    return data["ForeverChronicleDB"]["characters"][GUID]["snapshots"]["professions"]["list"]


def leatherworking(data):
    return next(p for p in professions_of(data) if p["skillLine"] == 165)


def test_recipe_parsing():
    # format 1 (addon v0.10.0, no quality)
    assert Recipe.parse("2881,2550,134252,Light Leather") == Recipe(2881, 2550, 134252, "Light Leather")
    assert Recipe.parse("100,,,Pattern: Hide, Cured") == Recipe(100, None, None, "Pattern: Hide, Cured")
    assert Recipe.parse("abc,1,2,x") is None and Recipe.parse("1,2,3") is None and Recipe.parse("1,2,3,") is None
    # format 2: quality before the name
    assert Recipe.parse("9058,2552,133150,2,Handstitched Leather Cloak", 2) ==         Recipe(9058, 2552, 133150, "Handstitched Leather Cloak", 2)
    assert Recipe.parse("100,,,,Enchant Bracer, Minor", 2) == Recipe(100, None, None, "Enchant Bracer, Minor", None)
    assert Recipe.parse("100,1,2,x,Name", 2) is None and Recipe.parse("100,1,2,Name", 2) is None
    assert RecipeCategory.parse("2549,,Leatherworking") == RecipeCategory(2549, None, "Leatherworking")
    assert RecipeCategory.parse("2550,2549,Materials") == RecipeCategory(2550, 2549, "Materials")


def test_import_professions(db, data):
    result = SavedVariablesImporter(db).import_data(data, "fixture")
    assert result.status == "ok" and result.invalid == 0 and result.recipes == 4
    repo = Repository(db.conn)
    cid = repo.list_characters()[0].character_id

    profs = repo.professions(cid)
    assert [p["name"] for p in profs] == ["Herbalism", "Leatherworking", "Cooking", "First Aid"]  # primary first
    lw = next(p for p in profs if p["skill_line"] == 165)
    assert (lw["rank"], lw["max_rank"], lw["kind"], lw["recipe_status"], lw["recipes_total"], lw["recipe_count"]) == \
        (126, 150, "primary", "complete", 6, 4)
    herb = next(p for p in profs if p["skill_line"] == 182)
    assert herb["recipe_status"] is None and herb["recipe_count"] == 0

    recipes = repo.recipes(cid)
    assert [(r["name"], r["category"], r["quality"]) for r in recipes] == [
        ("Handstitched Leather Cloak", "Cloaks", 2), ("Cured Light Hide", "Materials", 1),
        ("Cured Medium Hide", "Materials", 1), ("Light Leather", "Materials", 1)]
    assert [r["name"] for r in repo.recipes(cid, search="hide")] == ["Cured Light Hide", "Cured Medium Hide"]
    assert repo.recipes(cid, skill_line=185) == []
    assert dict((s.key, v) for s, v in stats.compute_all(repo, cid))["recipes"] == 4

    # Importing the same file again changes nothing.
    SavedVariablesImporter(db).import_data(copy.deepcopy(data), "fixture")
    assert len(repo.recipes(cid)) == 4 and len(repo.professions(cid)) == 4


def test_partial_snapshot_never_removes_recipes(db, data):
    importer = SavedVariablesImporter(db)
    importer.import_data(copy.deepcopy(data), "fixture")
    repo = Repository(db.conn)
    cid = repo.list_characters()[0].character_id

    partial = copy.deepcopy(data)
    lw = leatherworking(partial)
    lw["recipes"]["status"] = "partial"
    lw["recipes"]["list"] = ["2149,2553,132539,2,Handstitched Leather Boots"]
    importer.import_data(partial, "partial")
    assert len(repo.recipes(cid, skill_line=165)) == 5
    assert next(p for p in repo.professions(cid) if p["skill_line"] == 165)["recipe_status"] == "partial"

    complete = copy.deepcopy(data)
    leatherworking(complete)["recipes"]["list"] = ["2881,2550,134252,,Light Leather"]  # quality unknown this time
    importer.import_data(complete, "complete")
    assert [(r["name"], r["quality"]) for r in repo.recipes(cid, skill_line=165)] == [("Light Leather", 1)]  # kept


def test_unlearned_profession_and_invalid_records(db, data):
    changed = copy.deepcopy(data)
    leatherworking(changed)["active"] = False
    professions_of(changed).append({"skillLine": "x", "name": 5})
    professions_of(changed).append({"skillLine": 999, "name": "Broken", "recipes": {"status": "weird", "list": []}})
    leatherworking(changed)["recipes"]["list"].append("not a recipe")
    result = SavedVariablesImporter(db).import_data(changed, "fixture")
    assert result.status == "partial" and result.invalid == 3
    repo = Repository(db.conn)
    cid = repo.list_characters()[0].character_id
    assert 165 not in [p["skill_line"] for p in repo.professions(cid)]
    assert 165 in [p["skill_line"] for p in repo.professions(cid, include_inactive=True)]
    assert repo.recipes(cid) == []  # recipes of unlearned professions are hidden


def test_profession_event_texts():
    from forever_chronicle.storage.repository import EventRow
    def event(kind, payload):
        return EventRow("c", "e", kind, 0, None, None, None, None, None, payload)
    assert event_types.describe(event("profession_rank", {"name": "Leatherworking", "maxRank": 225})) == \
        "Leatherworking: Experte"
    assert event_types.describe(event("profession_rank", {"name": "Mining", "maxRank": 375})) == "Mining: 375"
    assert event_types.describe(event("recipe_learned", {"recipeID": 2149})) == "Rezept gelernt: #2149"
    assert event_types.describe(event("profession_learned", {"name": "Fishing"})) == "Beruf erlernt: Fishing"
