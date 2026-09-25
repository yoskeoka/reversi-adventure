//! Diagnostic-only ordered search trace and inclusive cost counters.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::time::Instant;

use serde_json::{json, Value};
use sha2::{Digest, Sha256};

#[derive(Default)]
struct State {
    trace: Sha256,
    events: u64,
    counters: BTreeMap<&'static str, (u64, u128)>,
}

thread_local! {
    static STATE: RefCell<State> = RefCell::new(State::default());
}

pub fn reset() {
    STATE.with(|state| *state.borrow_mut() = State::default());
}

pub fn event(tag: u8, values: &[u64]) {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        state.trace.update([tag]);
        state.trace.update((values.len() as u64).to_le_bytes());
        for value in values {
            state.trace.update(value.to_le_bytes());
        }
        state.events += 1;
    });
}

pub fn measure<T>(category: &'static str, action: impl FnOnce() -> T) -> T {
    let started = Instant::now();
    let result = action();
    let elapsed = started.elapsed().as_nanos();
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        let counter = state.counters.entry(category).or_default();
        counter.0 += 1;
        counter.1 += elapsed;
    });
    result
}

pub fn snapshot() -> Value {
    STATE.with(|state| {
        let state = state.borrow();
        json!({
            "trace_sha256": format!("{:x}", state.trace.clone().finalize()),
            "trace_events": state.events,
            "counters": state.counters.iter().map(|(key, (count, elapsed_ns))| {
                ((*key).to_string(), json!({"calls": count, "inclusive_ns": elapsed_ns}))
            }).collect::<BTreeMap<_, _>>(),
        })
    })
}
