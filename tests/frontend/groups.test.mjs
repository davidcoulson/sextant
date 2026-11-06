// Who gets a heading in the Live page's list (sextant-groups.js personGroups).
// Run: node --test tests/frontend
import { test } from "node:test";
import assert from "node:assert/strict";
import { personGroups } from "../../custom_components/sextant/frontend/sextant-groups.js";

const row = (ent) => ({ ent });
const rows = ["mika_phone", "emilie_watch", "spirit_tag", "suky_tag", "wallet", "vacuum"].map(row);

// The reference house: two people back from one phone each, named after them,
// two cats on their own tags, an unowned wallet and the vacuum.
const owners = { mika_phone: "person.mika", emilie_watch: "person.emilie", spirit_tag: "person.spirit", suky_tag: "person.suky" };
const classes = { mika_phone: "phone", emilie_watch: "watch", spirit_tag: "cat", suky_tag: "paw", vacuum: "robot" };

test("one thing is enough for a person's section, even named after them", () => {
  const { groups, pets, rest } = personGroups(rows, owners, classes);
  assert.deepEqual(groups.map((g) => g.person), ["person.mika", "person.emilie"]);
  assert.deepEqual(groups.map((g) => g.list.map((p) => p.ent)), [["mika_phone"], ["emilie_watch"]]);
  assert.deepEqual(pets.map((p) => p.ent), ["spirit_tag", "suky_tag"]);
  assert.deepEqual(rest.map((p) => p.ent), ["wallet", "vacuum"]);
});

test("a pet keeps no heading: their own tag is a plain row under Pets", () => {
  // Spirit owns only a cat tag - and would say nothing twice with a heading
  // over a row already reading "Spirit".
  const { groups, pets } = personGroups([row("spirit_tag")], { spirit_tag: "person.spirit" }, { spirit_tag: "cat" });
  assert.deepEqual(groups, []);
  assert.deepEqual(pets.map((p) => p.ent), ["spirit_tag"]);
});

test("a person with a pet-class thing and a phone keeps their section", () => {
  const mixed = [row("phone"), row("cat_tag")];
  const { groups, pets, rest } = personGroups(mixed, { phone: "person.mika", cat_tag: "person.mika" }, { phone: "phone", cat_tag: "cat" });
  assert.deepEqual(groups.map((g) => g.list.map((p) => p.ent)), [["phone", "cat_tag"]]);
  assert.deepEqual(pets, []);
  assert.deepEqual(rest, []);
});

test("with no owners at all everything is a plain row", () => {
  const { groups, pets, rest } = personGroups(rows, {}, classes);
  assert.deepEqual(groups, []);
  assert.deepEqual(pets.map((p) => p.ent), ["spirit_tag", "suky_tag"]);
  assert.deepEqual(rest.map((p) => p.ent), ["mika_phone", "emilie_watch", "wallet", "vacuum"]);
});

test("an owner that is not a person entity does not group", () => {
  const { groups, rest } = personGroups([row("a"), row("b")], { a: "person.x", b: "someting.else" }, {});
  assert.deepEqual(groups.map((g) => g.person), ["person.x"]);
  assert.deepEqual(rest.map((p) => p.ent), ["b"]);
});
