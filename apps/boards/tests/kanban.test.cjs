const assert = require("node:assert/strict");
const {readFileSync} = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = readFileSync(path.join(__dirname, "../../../static/js/kanban.js"), "utf8");

// A small browser API fixture exercises the actual event handlers, including
// async fetch/dragend ordering, without adding a frontend build dependency.
function fixture(fetchResult = async () => ({ok: true, json: async () => ({ok: true})})) {
    const listeners = {};
    const requests = [];
    const timers = [];
    let reloads = 0;
    const classes = () => {
        const values = new Set();
        return {
            add: (name) => values.add(name),
            remove: (name) => values.delete(name),
            contains: (name) => values.has(name),
            toggle: (name, enabled) => enabled ? values.add(name) : values.delete(name),
        };
    };
    const makeCard = (id) => ({
        dataset: {taskId: String(id), moveUrl: `/tasks/${id}/move/`},
        draggable: true,
        classList: classes(),
        offsetHeight: 100,
        closest(selector) { return selector === "[data-task-id]" ? this : this.parentNode; },
        get nextSibling() {
            const children = this.parentNode.children;
            return children[children.indexOf(this) + 1] || null;
        },
        getBoundingClientRect() { return {top: this.parentNode.children.indexOf(this) * 100}; },
    });
    const makeList = (id, children) => {
        const list = {
            dataset: {columnId: String(id)}, children,
            empty: children.length ? null : {hidden: false},
            closest: () => list,
            querySelector(selector) {
                return selector === "[data-empty-state]" ? this.empty : this.children[0];
            },
            querySelectorAll(selector) {
                return this.children.filter((card) =>
                    !selector.includes(":not") || !card.classList.contains("is-dragging"));
            },
            insertBefore(card, next) {
                const previous = card.parentNode.children;
                previous.splice(previous.indexOf(card), 1);
                const index = next === null ? this.children.length : this.children.indexOf(next);
                assert.ok(index >= 0, "The original next sibling must remain in its list");
                this.children.splice(index, 0, card);
                card.parentNode = this;
            },
        };
        children.forEach((card) => { card.parentNode = list; });
        return list;
    };
    const cards = [1, 2, 3].map(makeCard);
    const lists = [makeList(10, cards.slice()), makeList(20, [])];
    const status = {textContent: "", classList: classes()};
    const board = {
        dataset: {canMove: "true"},
        addEventListener: (name, handler) => { listeners[name] = handler; },
        querySelectorAll: () => lists,
    };
    vm.runInNewContext(source, {
        document: {
            cookie: "csrftoken=test-token",
            querySelector: (selector) => selector === "[data-kanban-board]" ? board : status,
        },
        fetch: (...args) => { requests.push(args); return fetchResult(...args); },
        window: {
            setTimeout: (callback) => timers.push(callback),
            location: {reload: () => { reloads += 1; }},
        },
    });
    const event = (target, extra = {}) => ({
        target, clientY: 1000, prevented: false,
        preventDefault() { this.prevented = true; },
        dataTransfer: {setData() {}}, ...extra,
    });
    return {
        cards, lists, requests, timers, status, event,
        emit: (name, input) => listeners[name](input),
        order: () => lists.map((list) => list.children.map((card) => card.dataset.taskId)),
        reloads: () => reloads,
    };
}

for (const index of [0, 1, 2]) {
    test(`canceled cross-column drag restores card ${index + 1} and empty state`, () => {
        const ui = fixture();
        const original = ui.order();
        ui.emit("dragstart", ui.event(ui.cards[index]));
        ui.emit("dragover", ui.event(ui.lists[1]));
        assert.equal(ui.lists[1].empty.hidden, true);
        ui.emit("dragend", ui.event(ui.cards[index]));
        assert.deepEqual(ui.order(), original);
        assert.equal(ui.lists[1].empty.hidden, false);
        assert.equal(ui.cards[index].classList.contains("is-dragging"), false);
        assert.equal(ui.requests.length, 0);
    });
}

test("canceling a reorder in the same column restores the original order", () => {
    const ui = fixture();
    ui.emit("dragstart", ui.event(ui.cards[0]));
    ui.emit("dragover", ui.event(ui.lists[0]));
    assert.deepEqual(ui.order()[0], ["2", "3", "1"]);
    ui.emit("dragend", ui.event(ui.cards[0]));
    assert.deepEqual(ui.order()[0], ["1", "2", "3"]);
});

for (const [name, fetchResult] of [
    ["server rejection", async () => ({ok: false, json: async () => ({error: "رد شد"})})],
    ["network failure", async () => { throw new Error("network unavailable"); }],
    ["non-JSON response", async () => ({ok: false, json: async () => { throw new Error("HTML"); }})],
]) {
    test(`${name} restores the captured position after dragend and refreshes server state`, async () => {
        const ui = fixture(fetchResult);
        const original = ui.order();
        ui.emit("dragstart", ui.event(ui.cards[1]));
        ui.emit("dragover", ui.event(ui.lists[1]));
        const pending = ui.emit("drop", ui.event(ui.lists[1]));
        ui.emit("dragend", ui.event(ui.cards[1]));
        await pending;
        assert.deepEqual(ui.order(), original);
        assert.equal(ui.lists[1].empty.hidden, false);
        assert.equal(ui.status.classList.contains("is-error"), true);
        const blocked = ui.event(ui.cards[0]);
        ui.emit("dragstart", blocked);
        assert.equal(blocked.prevented, true);
        assert.equal(ui.timers.length, 1);
        ui.timers[0]();
        assert.equal(ui.reloads(), 1);
    });
}

test("successful drop preserves the new position and blocks overlapping saves", async () => {
    let finish;
    const ui = fixture(() => new Promise((resolve) => { finish = resolve; }));
    ui.emit("dragstart", ui.event(ui.cards[1]));
    ui.emit("dragover", ui.event(ui.lists[1]));
    const pending = ui.emit("drop", ui.event(ui.lists[1]));
    ui.emit("dragend", ui.event(ui.cards[1]));
    const blocked = ui.event(ui.cards[0]);
    ui.emit("dragstart", blocked);
    assert.equal(blocked.prevented, true);
    finish({ok: true, json: async () => ({ok: true, column: 20, position: 0})});
    await pending;
    assert.deepEqual(ui.order(), [["1", "3"], ["2"]]);
    assert.equal(ui.requests.length, 1);
    const [url, options] = ui.requests[0];
    assert.equal(url, "/tasks/2/move/");
    assert.equal(options.method, "POST");
    assert.equal(options.headers["X-CSRFToken"], "test-token");
    assert.deepEqual(JSON.parse(options.body), {column: 20, position: 0});
    assert.equal(ui.timers.length, 0);
    const allowed = ui.event(ui.cards[0]);
    ui.emit("dragstart", allowed);
    assert.equal(allowed.prevented, false);
    ui.emit("dragend", ui.event(ui.cards[0]));
    assert.deepEqual(ui.order(), [["1", "3"], ["2"]]);
});
