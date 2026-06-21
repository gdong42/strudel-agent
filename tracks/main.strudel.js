const mood = {
  bpm: 128,
  key: 'c minor',
  color: 'late-night deep house with a soft ambient haze',
  bass: 'c2 ~ c2 eb2 ~ g1 bb1 ~',
  chords: [
    ['c4', 'eb4', 'g4', 'bb4'],
    ['f4', 'ab4', 'c5', 'eb5'],
    ['ab3', 'c4', 'eb4', 'g4'],
    ['g3', 'b3', 'd4', 'f4'],
  ],
};

// 128 BPM, treating one cycle as one four-beat bar.
setcpm(mood.bpm / 4);

stack(
  s("bd*4 [bd ~]")
    .gain(0.78)
    .color('white')
    .punchcard({
      cycles: 4,
      playhead: 0.18,
      fill: 1,
      hideInactive: 0,
      background: 'rgba(16,18,20,0.35)',
      active: '#ffca28',
      inactive: '#40505f',
    }),
  s("~ hh ~ hh ~ hh [~ hh]").gain("[0.34 0.46 0.32 0.52]").decay(0.42),
  s("~ cp ~ <cp [cp cp]>").gain(0.66).room(0.28),
  s("hh*16").gain("[0.18 0.3]*8"),
  s("~ ~ [sd ~] ~, ~ cp ~ [~ cp]")
    .gain(0.22)
    .speed("<1 1.5 1 0.75>"),
  note("<c2 ~ c2 eb3 ~ g1 bb1 ~ c2 [c2 eb2] [eb2 c2] ~ g1 [bb1 c2]>")
    .s("sawtooth")
    .gain(0.48)
    .cutoff("[620 760 680 840]")
    .decay(0.14)
    .scope({
      pos: 0.2,
      scale: 0.42,
      thickness: 3,
      color: '#7ce7d8',
      align: 1,
    }),
  stack(
    note("~ <[c4,eb4,g4,bb4] [f4,ab4,c5,eb5]> ~ <[ab3,c4,eb4,g4] [g3,b3,d4,f4]>")
  )
    .s("triangle")
    .gain("[0.28 0.42 0.22 0.36]")
    .attack(0.01)
    .decay("<0.14 0.2 0.12 0.18>")
    .sustain(0.15)
    .release(0.12)
    .delay(0.12)
    .color("<magenta yellow cyan white>")
    .spiral({
      steady: 0.96,
      thickness: 8,
      activeColor: '#8bd3ff',
      inactiveColor: '#32424f',
      playheadColor: '#ffffff',
    }),
  stack(
    note("<[c4,eb4,g4,bb4] [f4,ab4,c5,eb5] [ab3,c4,eb4,g4] [g3,b3,d4,f4]>/4")
  )
    .s("sine")
    .gain(0.11)
    .attack(1.2)
    .release(3.5)
    .hpf(320)
    .room(0.75)
    .delay(0.35)
    .color("<lightblue cyan white>")
    ._pianoroll({
      cycles: 2,
      playhead: 0.5,
      fill: 1,
      stroke: 1,
      active: '#9ee7ff',
      inactive: '#334c5c',
      background: 'rgba(10,12,14,0.15)',
      autorange: 1,
    })
)
