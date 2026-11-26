use sha2::{Digest, Sha256};
use std::fs;

fn main() {
    for (file, expected) in [
        (
            "data/xot/openingslarge.txt",
            "ccbeb0ed7b7ae23de20013a3992b9a6ede77610bbb5cacda82ccbaedaab72530",
        ),
        (
            "data/xot/openingssmall.txt",
            "8a441b077b1093af7b0d1cb55fa5a0d3d1700ce200a1b2d5b6e28d7b17139580",
        ),
    ] {
        println!("cargo:rerun-if-changed={file}");
        let bytes = fs::read(file).unwrap_or_else(|err| panic!("{file}: {err}"));
        let actual = format!("{:x}", Sha256::digest(bytes));
        assert_eq!(actual, expected, "XOT source digest mismatch for {file}");
    }
}
