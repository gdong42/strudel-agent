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
  // Kick — deep house groove: four-on-the-floor with syncopated ghost kicks
  s("bd [~ bd] bd [~ bd] [bd ~] bd [~ bd] ~")
    .gain("[0.82 0.42 0.78 0.38 0.76 0.44 0.72 0.34]")
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
  // Main hi-hats — off-beat groove with open-hat accents
  s("~ hh ~ hh [oh hh] hh [~ hh] ~")
    .gain("[0.36 0.48 0.54 0.42 0.44 0.38 0.50 0.30]")
    .decay("[0.18 0.12 0.28 0.10 0.18 0.12 0.22 0.10]"),
  s("~ cp ~ <cp [cp cp]>").gain(0.66).room(0.28),
  // Shimmer hats — velocity-shaped 16ths with shuffle feel
  s("hh*16")
    .gain("[0.12 0.28 0.14 0.32 0.12 0.26 0.14 0.30 0.12 0.28 0.14 0.34 0.10 0.24 0.14 0.28]")
    .decay(0.08),
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
    }),
  // Arp — single-note arpeggio with irregular rhythmic groupings per chord
  note("<[c5 eb5 g5 bb5 c6] [f5 ab5 c6 eb6 f5] [ab4 c5 eb5 g5] [g4 b4 d5 f5 g5]>")
    .s("square")
    .gain(0.38)
    .attack(0.005)
    .decay("<0.06 0.09 0.06 0.08>")
    .sustain(0.02)
    .release(0.06)
    .cutoff(2400)
    .room(0.35)
    .delay(0.22)
    .pan("<0.3 0.7 0.5 0.4>")
    .color("#f0c060")
    ._pianoroll({
      cycles: 2,
      playhead: 0.5,
      fill: 1,
      stroke: 1,
      active: '#f0c060',
      inactive: '#4a3a28',
      background: 'rgba(10,12,14,0.12)',
      autorange: 1,
    })
)
