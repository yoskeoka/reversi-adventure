# table32 feature catalog

固定revisionのgeometry数学定義。table順、各placementの座標順（先頭が三進最上位桁）、reverse置換を固定する。各tableの4配置は同じparameter表を参照する。最後に手番側石数0..64を追加する。

Source: https://github.com/Nyanyan/Egaroucid/blob/67aa89f18bfd22fa35730cdc0a9f4e7501c2239a/src/tools/evaluation/evaluation_definition_20241125_1_7_5.hpp

| Table | Placements (ordered) | Reverse permutation |
| --- | --- | --- |
| hv2 | a2 b2 c2 d2 e2 f2 g2 h2; b1 b2 b3 b4 b5 b6 b7 b8; a7 b7 c7 d7 e7 f7 g7 h7; g1 g2 g3 g4 g5 g6 g7 g8 | 7,6,5,4,3,2,1,0 |
| d6+2C+X | b1 c1 d2 e3 g2 f4 g5 h6 h7; h2 h3 g4 f5 g7 e6 d7 c8 b8; g8 f8 e7 d6 b7 c5 b4 a3 a2; a7 a6 b5 c4 b2 d3 e2 f1 g1 | 8,7,6,5,4,3,2,1,0 |
| hv3 | a3 b3 c3 d3 e3 f3 g3 h3; c1 c2 c3 c4 c5 c6 c7 c8; a6 b6 c6 d6 e6 f6 g6 h6; f1 f2 f3 f4 f5 f6 f7 f8 | 7,6,5,4,3,2,1,0 |
| d7+2corner | a1 b1 c2 d3 e4 f5 g6 h7 h8; h1 h2 g3 f4 e5 d6 c7 b8 a8; h8 g8 f7 e6 d5 c4 b3 a2 a1; a8 a7 b6 c5 d4 e3 f2 g1 h1 | 8,7,6,5,4,3,2,1,0 |
| hv4 | a4 b4 c4 d4 e4 f4 g4 h4; d1 d2 d3 d4 d5 d6 d7 d8; a5 b5 c5 d5 e5 f5 g5 h5; e1 e2 e3 e4 e5 e6 e7 e8 | 7,6,5,4,3,2,1,0 |
| corner9 | a1 b1 c1 a2 b2 c2 a3 b3 c3; h1 g1 f1 h2 g2 f2 h3 g3 f3; a8 b8 c8 a7 b7 c7 a6 b6 c6; h8 g8 f8 h7 g7 f7 h6 g6 f6 | 0,3,6,1,4,7,2,5,8 |
| d5+2X | b2 d1 e2 f3 g4 h5 g7; g2 h4 g5 f6 e7 d8 b7; g7 e8 d7 c6 b5 a4 b2; b7 a5 b4 c3 d2 e1 g2 | 6,5,4,3,2,1,0 |
| d8+2C | a1 b2 c3 d4 e5 f6 g7 h8 a2 b1; h8 g7 f6 e5 d4 c3 b2 a1 h7 g8; h1 g2 f3 e4 d5 c6 b7 a8 h2 g1; a8 b7 c6 d5 e4 f3 g2 h1 a7 b8 | 0,1,2,3,4,5,6,7,9,8 |
| edge+2X | b2 a1 b1 c1 d1 e1 f1 g1 h1 g2; b2 a1 a2 a3 a4 a5 a6 a7 a8 b7; b7 a8 b8 c8 d8 e8 f8 g8 h8 g7; g2 h1 h2 h3 h4 h5 h6 h7 h8 g7 | 9,8,7,6,5,4,3,2,1,0 |
| triangle | a1 b1 c1 d1 a2 b2 c2 a3 b3 a4; h1 g1 f1 e1 h2 g2 f2 h3 g3 h4; a8 b8 c8 d8 a7 b7 c7 a6 b6 a5; h8 g8 f8 e8 h7 g7 f7 h6 g6 h5 | 0,4,7,9,1,5,8,2,6,3 |
| corner+block | a1 c1 d1 e1 f1 h1 c2 d2 e2 f2; a1 a3 a4 a5 a6 a8 b3 b4 b5 b6; a8 c8 d8 e8 f8 h8 c7 d7 e7 f7; h1 h3 h4 h5 h6 h8 g3 g4 g5 g6 | 5,4,3,2,1,0,9,8,7,6 |
| cross | a1 b2 c3 d4 b1 c2 d3 a2 b3 c4; h1 g2 f3 e4 g1 f2 e3 h2 g3 f4; a8 b7 c6 d5 b8 c7 d6 a7 b6 c5; h8 g7 f6 e5 g8 f7 e6 h7 g6 f5 | 0,1,2,3,7,8,9,4,5,6 |
| edge+Y | c2 a1 b1 c1 d1 e1 f1 g1 h1 f2; b3 a1 a2 a3 a4 a5 a6 a7 a8 b6; c7 a8 b8 c8 d8 e8 f8 g8 h8 f7; g3 h1 h2 h3 h4 h5 h6 h7 h8 g6 | 9,8,7,6,5,4,3,2,1,0 |
| narrow-triangle | a1 b1 c1 d1 e1 a2 b2 a3 a4 a5; h1 g1 f1 e1 d1 h2 g2 h3 h4 h5; a8 b8 c8 d8 e8 a7 b7 a6 a5 a4; h8 g8 f8 e8 d8 h7 g7 h6 h5 h4 | 0,5,7,8,9,1,6,2,3,4 |
| fish | a1 b1 a2 b2 c2 d2 b3 c3 b4 d4; h1 g1 h2 g2 f2 e2 g3 f3 g4 e4; a8 b8 a7 b7 c7 d7 b6 c6 b5 d5; h8 g8 h7 g7 f7 e7 g6 f6 g5 e5 | 0,2,1,3,6,8,4,7,5,9 |
| anvil | c6 d6 d7 d8 c8 f8 e8 e7 e6 f6; c3 c4 b4 a4 a3 a6 a5 b5 c5 c6; f3 e3 e2 e1 f1 c1 d1 d2 d3 c3; f6 f5 g5 h5 h6 h3 h4 g4 f4 f3 | 9,8,7,6,5,4,3,2,1,0 |
