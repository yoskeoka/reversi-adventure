use godot::prelude::*;

mod bridge;

struct ReversiExtension;

#[gdextension]
unsafe impl ExtensionLibrary for ReversiExtension {}
