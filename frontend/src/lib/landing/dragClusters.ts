/**
 * The draggable course clusters that float over the lower sections.
 *
 * Extracted from the v5 design component, where each cluster is ~2KB of
 * hand-written inline SVG, repeated eight times. The geometry is the same
 * shape in every one -- a course puck, two or three concept nodes, and the
 * edges between them -- so it lives here as data and is drawn by a single
 * component.
 *
 * The oversized svg box and its negative margin are deliberate: the sim
 * throws nodes well outside the nominal bounds when dragged, and a tight
 * viewBox would clip them mid-flight.
 */

export interface ClusterNode { cx: number; cy: number; r: number; fo: number; sw: number }
export interface ClusterLabel { text: string; x: number; y: number }
export interface ClusterLine { x1: number; y1: number; x2: number; y2: number; w: number }

export interface DragCluster {
  id: number;
  /** Which section's field this cluster belongs to. */
  section: 'act-tutor' | 'faq' | 'newsletter' | 'cta';
  pos: { left?: string; right?: string; top?: string; bottom?: string };
  /** The float keyframe, negative delay already baked in. */
  anim: string;
  color: string;
  code: string;
  svg: { w: number; h: number; vb: string };
  /** Where the course code sits. */
  codeAt: [number, number];
  nodes: ClusterNode[];
  labels: ClusterLabel[];
  lines: ClusterLine[];
}

export const DRAG_CLUSTERS: DragCluster[] = [
  {
    "id": 2,
    "section": "act-tutor",
    "pos": {
      "right": "6px",
      "top": "20%"
    },
    "anim": "nodeFloatA 21s ease-in-out -5.4s infinite",
    "color": "hsl(212 42% 42%)",
    "code": "MA 242",
    "svg": {
      "w": 1974,
      "h": 3418,
      "vb": "-900 -1600 1974 3418"
    },
    "codeAt": [
      76.0,
      77.0
    ],
    "nodes": [
      {
        "cx": 76.0,
        "cy": 44.0,
        "r": 18.0,
        "fo": 0.78,
        "sw": 2.5
      },
      {
        "cx": 106.0,
        "cy": 104.0,
        "r": 10.2,
        "fo": 0.55,
        "sw": 1.5
      },
      {
        "cx": 130.0,
        "cy": 162.0,
        "r": 7.5,
        "fo": 0.28,
        "sw": 1.5
      },
      {
        "cx": 44.0,
        "cy": 100.0,
        "r": 11.9,
        "fo": 0.78,
        "sw": 1.5
      }
    ],
    "labels": [
      {
        "text": "Eigenvalues",
        "x": 106.0,
        "y": 126.2
      },
      {
        "text": "Diagonalize",
        "x": 130.0,
        "y": 181.4
      },
      {
        "text": "Determinants",
        "x": 44.0,
        "y": 124.0
      }
    ],
    "lines": [
      {
        "x1": 76.0,
        "y1": 44.0,
        "x2": 106.0,
        "y2": 104.0,
        "w": 1.52
      },
      {
        "x1": 106.0,
        "y1": 104.0,
        "x2": 130.0,
        "y2": 162.0,
        "w": 1.04
      },
      {
        "x1": 76.0,
        "y1": 44.0,
        "x2": 44.0,
        "y2": 100.0,
        "w": 1.28
      }
    ]
  },
  {
    "id": 3,
    "section": "act-tutor",
    "pos": {
      "left": "6px",
      "top": "64%"
    },
    "anim": "nodeFloatB 24s ease-in-out -8.100000000000001s infinite",
    "color": "hsl(58 44% 38%)",
    "code": "ME 218",
    "svg": {
      "w": 1940,
      "h": 3416,
      "vb": "-900 -1600 1940 3416"
    },
    "codeAt": [
      96.0,
      77.0
    ],
    "nodes": [
      {
        "cx": 96.0,
        "cy": 44.0,
        "r": 18.0,
        "fo": 0.78,
        "sw": 2.5
      },
      {
        "cx": 66.0,
        "cy": 102.0,
        "r": 12.2,
        "fo": 0.78,
        "sw": 1.5
      },
      {
        "cx": 44.0,
        "cy": 160.0,
        "r": 14.6,
        "fo": 1.0,
        "sw": 1.5
      }
    ],
    "labels": [
      {
        "text": "Free-body",
        "x": 66.0,
        "y": 126.2
      },
      {
        "text": "Statics",
        "x": 44.0,
        "y": 186.6
      }
    ],
    "lines": [
      {
        "x1": 96.0,
        "y1": 44.0,
        "x2": 66.0,
        "y2": 102.0,
        "w": 1.46
      },
      {
        "x1": 66.0,
        "y1": 102.0,
        "x2": 44.0,
        "y2": 160.0,
        "w": 1.22
      }
    ]
  },
  {
    "id": 4,
    "section": "faq",
    "pos": {
      "left": "6px",
      "top": "18%"
    },
    "anim": "nodeFloatA 15s ease-in-out -10.8s infinite",
    "color": "hsl(150 46% 34%)",
    "code": "CS 112",
    "svg": {
      "w": 1972,
      "h": 3418,
      "vb": "-900 -1600 1972 3418"
    },
    "codeAt": [
      96.0,
      77.0
    ],
    "nodes": [
      {
        "cx": 96.0,
        "cy": 44.0,
        "r": 18.0,
        "fo": 1.0,
        "sw": 2.5
      },
      {
        "cx": 66.0,
        "cy": 104.0,
        "r": 9.7,
        "fo": 0.55,
        "sw": 1.5
      },
      {
        "cx": 44.0,
        "cy": 162.0,
        "r": 7.5,
        "fo": 0.28,
        "sw": 1.5
      },
      {
        "cx": 128.0,
        "cy": 100.0,
        "r": 12.4,
        "fo": 0.78,
        "sw": 1.5
      }
    ],
    "labels": [
      {
        "text": "Recursion",
        "x": 66.0,
        "y": 125.7
      },
      {
        "text": "Memoize",
        "x": 44.0,
        "y": 181.4
      },
      {
        "text": "Heaps",
        "x": 128.0,
        "y": 124.4
      }
    ],
    "lines": [
      {
        "x1": 96.0,
        "y1": 44.0,
        "x2": 66.0,
        "y2": 104.0,
        "w": 1.46
      },
      {
        "x1": 66.0,
        "y1": 104.0,
        "x2": 44.0,
        "y2": 162.0,
        "w": 1.1
      },
      {
        "x1": 96.0,
        "y1": 44.0,
        "x2": 128.0,
        "y2": 100.0,
        "w": 1.34
      }
    ]
  },
  {
    "id": 5,
    "section": "faq",
    "pos": {
      "right": "6px",
      "bottom": "14%"
    },
    "anim": "nodeFloatB 18s ease-in-out -13.5s infinite",
    "color": "hsl(272 34% 46%)",
    "code": "PH 150",
    "svg": {
      "w": 1940,
      "h": 3416,
      "vb": "-900 -1600 1940 3416"
    },
    "codeAt": [
      44.0,
      77.0
    ],
    "nodes": [
      {
        "cx": 44.0,
        "cy": 44.0,
        "r": 18.0,
        "fo": 1.0,
        "sw": 2.5
      },
      {
        "cx": 74.0,
        "cy": 102.0,
        "r": 14.6,
        "fo": 1.0,
        "sw": 1.5
      },
      {
        "cx": 96.0,
        "cy": 160.0,
        "r": 11.5,
        "fo": 0.78,
        "sw": 1.5
      }
    ],
    "labels": [
      {
        "text": "Utilitarian",
        "x": 74.0,
        "y": 128.7
      },
      {
        "text": "Trolley",
        "x": 96.0,
        "y": 183.5
      }
    ],
    "lines": [
      {
        "x1": 44.0,
        "y1": 44.0,
        "x2": 74.0,
        "y2": 102.0,
        "w": 1.34
      },
      {
        "x1": 74.0,
        "y1": 102.0,
        "x2": 96.0,
        "y2": 160.0,
        "w": 1.1
      }
    ]
  },
  {
    "id": 6,
    "section": "newsletter",
    "pos": {
      "right": "6px",
      "top": "20%"
    },
    "anim": "nodeFloatA 21s ease-in-out -16.200000000000003s infinite",
    "color": "hsl(96 40% 38%)",
    "code": "BI 108",
    "svg": {
      "w": 1942,
      "h": 3418,
      "vb": "-900 -1600 1942 3418"
    },
    "codeAt": [
      44.0,
      77.0
    ],
    "nodes": [
      {
        "cx": 44.0,
        "cy": 44.0,
        "r": 18.0,
        "fo": 0.78,
        "sw": 2.5
      },
      {
        "cx": 74.0,
        "cy": 104.0,
        "r": 12.4,
        "fo": 0.78,
        "sw": 1.5
      },
      {
        "cx": 98.0,
        "cy": 162.0,
        "r": 9.5,
        "fo": 0.55,
        "sw": 1.5
      }
    ],
    "labels": [
      {
        "text": "Meiosis",
        "x": 74.0,
        "y": 128.4
      },
      {
        "text": "Crossover",
        "x": 98.0,
        "y": 183.5
      }
    ],
    "lines": [
      {
        "x1": 44.0,
        "y1": 44.0,
        "x2": 74.0,
        "y2": 104.0,
        "w": 1.34
      },
      {
        "x1": 74.0,
        "y1": 104.0,
        "x2": 98.0,
        "y2": 162.0,
        "w": 1.16
      }
    ]
  },
  {
    "id": 7,
    "section": "newsletter",
    "pos": {
      "left": "6px",
      "bottom": "16%"
    },
    "anim": "nodeFloatB 24s ease-in-out -18.900000000000002s infinite",
    "color": "hsl(240 28% 50%)",
    "code": "WR 120",
    "svg": {
      "w": 1940,
      "h": 3416,
      "vb": "-900 -1600 1940 3416"
    },
    "codeAt": [
      96.0,
      77.0
    ],
    "nodes": [
      {
        "cx": 96.0,
        "cy": 44.0,
        "r": 18.0,
        "fo": 1.0,
        "sw": 2.5
      },
      {
        "cx": 66.0,
        "cy": 102.0,
        "r": 14.7,
        "fo": 1.0,
        "sw": 1.5
      },
      {
        "cx": 44.0,
        "cy": 160.0,
        "r": 11.7,
        "fo": 0.78,
        "sw": 1.5
      }
    ],
    "labels": [
      {
        "text": "Thesis",
        "x": 66.0,
        "y": 128.7
      },
      {
        "text": "Counterarg.",
        "x": 44.0,
        "y": 183.7
      }
    ],
    "lines": [
      {
        "x1": 96.0,
        "y1": 44.0,
        "x2": 66.0,
        "y2": 102.0,
        "w": 1.34
      },
      {
        "x1": 66.0,
        "y1": 102.0,
        "x2": 44.0,
        "y2": 160.0,
        "w": 1.1
      }
    ]
  },
  {
    "id": 8,
    "section": "cta",
    "pos": {
      "left": "10px",
      "top": "20%"
    },
    "anim": "nodeFloatA 15s ease-in-out -21.6s infinite",
    "color": "hsl(28 52% 42%)",
    "code": "PY 205",
    "svg": {
      "w": 1974,
      "h": 3414,
      "vb": "-900 -1600 1974 3414"
    },
    "codeAt": [
      74.0,
      77.0
    ],
    "nodes": [
      {
        "cx": 74.0,
        "cy": 44.0,
        "r": 18.0,
        "fo": 0.78,
        "sw": 2.5
      },
      {
        "cx": 44.0,
        "cy": 104.0,
        "r": 9.3,
        "fo": 0.55,
        "sw": 1.5
      },
      {
        "cx": 106.0,
        "cy": 100.0,
        "r": 15.1,
        "fo": 1.0,
        "sw": 1.5
      },
      {
        "cx": 130.0,
        "cy": 158.0,
        "r": 11.9,
        "fo": 0.78,
        "sw": 1.5
      }
    ],
    "labels": [
      {
        "text": "Torque",
        "x": 44.0,
        "y": 125.3
      },
      {
        "text": "Kinematics",
        "x": 106.0,
        "y": 127.1
      },
      {
        "text": "Momentum",
        "x": 130.0,
        "y": 181.9
      }
    ],
    "lines": [
      {
        "x1": 74.0,
        "y1": 44.0,
        "x2": 44.0,
        "y2": 104.0,
        "w": 1.4
      },
      {
        "x1": 74.0,
        "y1": 44.0,
        "x2": 106.0,
        "y2": 100.0,
        "w": 1.22
      },
      {
        "x1": 106.0,
        "y1": 100.0,
        "x2": 130.0,
        "y2": 158.0,
        "w": 1.1
      }
    ]
  },
  {
    "id": 9,
    "section": "cta",
    "pos": {
      "right": "10px",
      "bottom": "18%"
    },
    "anim": "nodeFloatB 18s ease-in-out -24.3s infinite",
    "color": "hsl(0 38% 46%)",
    "code": "HI 210",
    "svg": {
      "w": 1940,
      "h": 3416,
      "vb": "-900 -1600 1940 3416"
    },
    "codeAt": [
      44.0,
      77.0
    ],
    "nodes": [
      {
        "cx": 44.0,
        "cy": 44.0,
        "r": 18.0,
        "fo": 0.55,
        "sw": 2.5
      },
      {
        "cx": 74.0,
        "cy": 102.0,
        "r": 9.0,
        "fo": 0.55,
        "sw": 1.5
      },
      {
        "cx": 96.0,
        "cy": 160.0,
        "r": 7.5,
        "fo": 0.28,
        "sw": 1.5
      }
    ],
    "labels": [
      {
        "text": "Reconstruction",
        "x": 74.0,
        "y": 123.0
      },
      {
        "text": "Reform acts",
        "x": 96.0,
        "y": 179.4
      }
    ],
    "lines": [
      {
        "x1": 44.0,
        "y1": 44.0,
        "x2": 74.0,
        "y2": 102.0,
        "w": 1.46
      },
      {
        "x1": 74.0,
        "y1": 102.0,
        "x2": 96.0,
        "y2": 160.0,
        "w": 1.04
      }
    ]
  }
// No `as DragCluster[]`. The annotation on the const already checks this
// literal, and the assertion suppressed exactly the two things worth catching
// in generated data: excess properties and missing required fields.
];
