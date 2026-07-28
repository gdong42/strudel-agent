const bpm = 124;
setcpm(bpm / 4);

/* @eval-region:drums:start */
const drums = stack(
  s("bd ~ bd ~").gain(0.78),
  s("~ hh ~ hh").gain(0.34),
  s("~ cp ~ cp").gain(0.5),
);
/* @eval-region:drums:end */

/* @eval-region:bass:start */
const bass = note("c2 ~ eb2 ~ g1 ~ bb1 ~")
  .s("sawtooth")
  .gain(0.48)
  .cutoff(740);
/* @eval-region:bass:end */

/* @eval-region:harmony:start */
const harmony = note("<[c4,eb4,g4,bb4] [f4,ab4,c5,eb5]>")
  .s("triangle")
  .gain(0.28)
  .room(0.28);
/* @eval-region:harmony:end */

/* @eval-region:pad:start */
const pad = note("<[c4,eb4,g4,bb4] [ab3,c4,eb4,g4]>/2")
  .s("sine")
  .gain(0.12)
  .hpf(300)
  .room(0.7);
/* @eval-region:pad:end */

/* @eval-region:visuals:start */
const visuals = s("~")
  .punchcard({ cycles: 4, playhead: 0.2, active: "#ffca28", inactive: "#40505f" });
/* @eval-region:visuals:end */

stack(drums, bass, harmony, pad, visuals);
