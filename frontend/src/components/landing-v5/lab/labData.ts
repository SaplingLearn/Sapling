/**
 * Fixture data for the eight feature-lab demos.
 *
 * Lifted verbatim from `FeatureLab.dc.html`, the separate design component
 * the landing page mounts inside the lab's right pane. Content and tuning
 * values only -- the behaviour lives in the demo components beside this.
 *
 * TIER here is the lab's own swatch set: `unexplored` is #C3CCC6, lighter
 * than the landing graph's #9a9a9a, because these sit on cream cards rather
 * than the dark act ground.
 */

export const TIER = { mastered:'#3a7d4e', learning:'#c89b5e', struggling:'#b25855', unexplored:'#C3CCC6' };

export const TYPE = { exam:'#b25855', project:'#c89b5e', homework:'#0E9E5A', quiz:'#4FA574', reading:'#8FBFA3' };

export const QUESTIONS = [
  { concept:'Eigenvalues', diff:'MEDIUM',
    text:'If A v = λ v for some non-zero v, what does λ tell you about what A does to v?',
    options:[
      { label:'A', text:'The angle that A rotates v through' },
      { label:'B', text:'The factor that A scales v by', correct:true },
      { label:'C', text:'The determinant of A' },
      { label:'D', text:'The rank of A' }],
    explain:'λ is a pure scale factor along v. An eigenvector\u2019s direction is unchanged by A — only its length is.' },
  { concept:'Eigenvalues', diff:'HARD',
    text:'Which equation do you solve to find the eigenvalues of a square matrix A?',
    options:[
      { label:'A', text:'det(A \u2212 \u03bbI) = 0', correct:true },
      { label:'B', text:'A \u2212 \u03bbI = 0' },
      { label:'C', text:'det(A) = \u03bb' },
      { label:'D', text:'A v = 0' }],
    explain:'Non-zero solutions of (A \u2212 \u03bbI)v = 0 exist exactly when A \u2212 \u03bbI is singular — that is, when its determinant vanishes.' },
  { concept:'Eigenvalues', diff:'HARD',
    text:'A 3\u00d73 matrix has eigenvalues 2, 2 and 5. What is det(A)?',
    options:[
      { label:'A', text:'9' },
      { label:'B', text:'20', correct:true },
      { label:'C', text:'4' },
      { label:'D', text:'Not determined by the eigenvalues' }],
    explain:'The determinant is the product of the eigenvalues counted with multiplicity: 2 \u00b7 2 \u00b7 5 = 20.' },
];

export const DECK = [
  { q:'What equation gives the eigenvalues of A?', a:'det(A \u2212 \u03bbI) = 0 — the \u03bb that makes A \u2212 \u03bbI collapse.' },
  { q:'What is an eigenvector of A?', a:'A non-zero v whose direction A leaves alone: A v = \u03bb v.' },
  { q:'What does the eigenspace of \u03bb consist of?', a:'null(A \u2212 \u03bbI) — every v scaled by that \u03bb, plus the zero vector.' },
  { q:'When is a matrix diagonalizable?', a:'When its eigenvectors span the space — n independent eigenvectors for an n\u00d7n matrix.' },
];

export const RATE_DUE = { '1':'10 min', '2':'1 day', '3':'4 days' };

export const RATE_TONE = { '1':'#b25855', '2':'#c89b5e', '3':'#3a7d4e' };

export const RATE_LABEL = { '1':'Forgot', '2':'Hard', '3':'Easy' };

export const GUIDES = {
  'MA 242': {
    exams:['Midterm 2 \u00b7 Oct 24', 'Final \u00b7 Dec 12'],
    overview:'Built from 11 documents in your library. Weighted toward the concepts you have missed most in quizzes this month.',
    topics:[
      { name:'Eigenvalues & eigenvectors', tier:'struggling', weight:'42%', importance:'You missed 4 of 6 quiz questions here.',
        bullets:['Solve det(A \u2212 \u03bbI) = 0 for \u03bb, then null(A \u2212 \u03bbI) for the eigenspace.','Trace = sum of eigenvalues; determinant = their product.','Repeated \u03bb does not guarantee enough independent eigenvectors.'] },
      { name:'Determinants', tier:'learning', weight:'33%', importance:'Shaky on 3\u00d73 cofactor expansion.',
        bullets:['Expand along the row or column with the most zeros.','Row swaps flip the sign; scaling a row scales det.','det(AB) = det(A)det(B).'] },
      { name:'Vector spaces', tier:'mastered', weight:'25%', importance:'Solid — light review only.',
        bullets:['Check closure under addition and scalar multiplication.','rank + nullity = number of columns.'] }],
  },
  'CS 201': {
    exams:['Midterm 1 \u00b7 Oct 17', 'Final \u00b7 Dec 09'],
    overview:'Built from 7 documents in your library, weighted to the tree material you keep missing.',
    topics:[
      { name:'Balanced trees', tier:'struggling', weight:'48%', importance:'Rotations are your weakest concept in this course.',
        bullets:['Four rotation cases: LL, LR, RL, RR.','AVL re-balances on every insert; red-black amortizes.','Height stays O(log n) — that is the whole point.'] },
      { name:'Hashing', tier:'learning', weight:'30%', importance:'Two misses on collision handling.',
        bullets:['Good hash: uniform spread, cheap, deterministic.','Chaining vs open addressing trade space for locality.'] },
      { name:'Complexity', tier:'mastered', weight:'22%', importance:'Consistently correct — skim it.',
        bullets:['Amortized \u2260 average case.','Master theorem for divide-and-conquer recurrences.'] }],
  },
  'PY 105': {
    exams:['Midterm 2 \u00b7 Oct 21', 'Final \u00b7 Dec 15'],
    overview:'Built from 9 documents in your library, weighted to rotational dynamics.',
    topics:[
      { name:'Rotational dynamics', tier:'struggling', weight:'45%', importance:'Half your missed questions live here.',
        bullets:['\u03c4 = I\u03b1 is Newton\u2019s second law for rotation.','Parallel-axis theorem shifts I off the centre of mass.'] },
      { name:'Conservation laws', tier:'learning', weight:'32%', importance:'Momentum fine, energy accounting shaky.',
        bullets:['Check whether the collision is elastic before assuming KE holds.'] },
      { name:'Kinematics', tier:'mastered', weight:'23%', importance:'Solid.',
        bullets:['Pick the equation that omits the quantity you neither know nor want.'] }],
  },
};

export const GB_ROWS = [
  { title:'Pset 1 — Row reduction', cat:'PSETS', earned:47, possible:50 },
  { title:'Pset 2 — Determinants', cat:'PSETS', earned:44, possible:50 },
  { title:'Pset 3 — Eigenvalues', cat:'PSETS', earned:41, possible:50 },
  { title:'Midterm 1', cat:'MIDTERMS', earned:88, possible:100 },
  { title:'Midterm 2', cat:'MIDTERMS', earned:91, possible:100 },
];

export const GB_CATS = [ { name:'Psets', key:'PSETS', weight:0.40 }, { name:'Midterms', key:'MIDTERMS', weight:0.35 }, { name:'Final', key:'FINAL', weight:0.25 } ];

/** Grade bands, ordered high to low — the first match wins. */
export const LETTERS: [number, string][] = [[93,'A'],[90,'A\u2212'],[87,'B+'],[83,'B'],[80,'B\u2212'],[77,'C+'],[73,'C'],[70,'C\u2212'],[60,'D'],[0,'F']];

export const CAL_BASE = [
  { day:6, type:'homework', title:'Pset 4 — Eigenvalues', course:'MA 242' },
  { day:9, type:'quiz', title:'Quiz 3', course:'CS 201' },
  { day:15, type:'reading', title:'Ch. 6 — Diagonalization', course:'MA 242' },
];

export const CAL_SYLLABUS = [
  { day:2, type:'homework', title:'Pset 5 — Null spaces', course:'MA 242' },
  { day:11, type:'project', title:'Lab report 2', course:'PY 105' },
  { day:17, type:'reading', title:'Ch. 7 — Orthogonality', course:'MA 242' },
  { day:20, type:'quiz', title:'Quiz 4', course:'MA 242' },
  { day:24, type:'exam', title:'Midterm 2', course:'MA 242' },
  { day:29, type:'homework', title:'Pset 6 — Least squares', course:'MA 242' },
];

export const GRAPH_NODES = [
  { id:'vs', name:'Vector spaces', x:70, y:70, mine:'mastered', partner:{ maya:'mastered', jack:'learning', priya:'mastered' } },
  { id:'det', name:'Determinants', x:150, y:150, mine:'learning', partner:{ maya:'mastered', jack:'struggling', priya:'learning' } },
  { id:'eig', name:'Eigenvalues', x:230, y:64, mine:'struggling', partner:{ maya:'mastered', jack:'struggling', priya:'struggling' } },
  { id:'diag', name:'Diagonalization', x:320, y:140, mine:'unexplored', partner:{ maya:'learning', jack:'unexplored', priya:'mastered' } },
  { id:'orth', name:'Orthogonality', x:360, y:56, mine:'mastered', partner:{ maya:'unexplored', jack:'mastered', priya:'unexplored' } },
];

export const GRAPH_EDGES = [ ['vs','det'], ['det','eig'], ['vs','eig'], ['eig','diag'], ['diag','orth'] ];

export const TUTOR = {
  socratic: {
    label:'SOCRATIC', topic:'AVL ROTATIONS', tone:'#0E9E5A',
    blurb:'It never hands over the answer. Pick a reply and watch where it takes you.',
    open:'Before we touch rotations: what does an AVL tree promise about the heights of a node\u2019s two subtrees?',
    steps:[
      { replies:[
          { text:'They differ by at most one', bot:'Right. So when an insert makes them differ by two, the tree has to act. What is the cheapest thing it could change?' },
          { text:'They\u2019re always equal', bot:'Close, but stricter than reality. Perfect balance would cost too much on every insert. What is the loosest rule that still keeps height O(log n)?' },
          { text:'I don\u2019t know', bot:'Then start smaller. If a node\u2019s left subtree is height 5 and its right is height 1, does lookup still feel logarithmic to you?' }] },
      { replies:[
          { text:'Move one node up and one down', bot:'That is exactly a rotation. Now: after a left rotation, which node ends up as the new root of that subtree?' },
          { text:'Rebuild the whole subtree', bot:'It would work, but think about cost. Rebuilding is linear. Rotations are constant. What is the smallest edit that fixes the height?' }] },
      { replies:[
          { text:'The right child', bot:'Correct, and the old root becomes its left child. You just derived the rotation without being told it. Mastery on AVL rotations moved 24% \u2192 41%.' },
          { text:'The parent stays root', bot:'That is the most common wrong answer, and it is worth sitting with. If the parent stayed root, what would have changed about the heights?' }] },
    ],
  },
  expository: {
    label:'EXPOSITORY', topic:'AVL ROTATIONS', tone:'#4FA574',
    blurb:'Straight explanation, assembled from your own uploads and shown with its sources.',
    open:'An AVL tree keeps every node\u2019s balance factor in {\u22121, 0, +1}. When an insert pushes a node to \u00b12, exactly one of four rotations restores it in O(1): LL, LR, RL, RR.',
    sources:['lecture-07.pdf p. 12', 'notes-wk4.md'],
    steps:[
      { replies:[
          { text:'Show me the LL case', bot:'LL means the left child\u2019s left subtree is too tall. One right rotation: the left child rises to root, the old root becomes its right child, and the left child\u2019s right subtree reattaches as the old root\u2019s left.', sources:['lecture-07.pdf p. 13'] },
          { text:'Why not just rebuild?', bot:'Rebuilding is O(n) per insert. Rotations touch three pointers, so they are O(1), and the height guarantee holds either way. Constant beats linear on every insert.', sources:['lecture-07.pdf p. 12'] },
          { text:'How is this different from red-black?', bot:'AVL re-balances eagerly and stays more tightly balanced, so lookups are slightly faster. Red-black tolerates more skew and rotates less, so inserts are cheaper. Your syllabus compares them in week 5.', sources:['syllabus.pdf', 'notes-wk5.md'] }] },
      { replies:[
          { text:'Give me a worked example', bot:'Insert 30, 20, 10. After 10, node 30 has balance +2 with the skew on its left-left. Right-rotate at 30: 20 becomes root, 10 its left child, 30 its right. Heights are 1 and 1.', sources:['lecture-07.pdf p. 14'] },
          { text:'Quiz me instead', bot:'Then open the quiz surface from the rail. It will draw questions targeted at this node, since AVL rotations is your lowest-mastery concept in Trees.' }] },
    ],
  },
  teachback: {
    label:'TEACHBACK', topic:'AVL ROTATIONS', tone:'#E27A63',
    blurb:'You do the explaining. It listens for the part you skipped.',
    open:'Explain a left rotation to me as if I have never seen one. I will tell you exactly where it breaks down.',
    steps:[
      { replies:[
          { text:'The right side gets heavy, so the parent moves down', bot:'Direction is right, and you named the trigger correctly. But you skipped the part that matters: you said the parent moves down without saying what takes its place. Which node becomes the new root?' },
          { text:'You rotate until it\u2019s balanced', bot:'That describes the goal, not the mechanism. A grader would not give credit. Walk me through the pointers: what happens to the root, the right child, and the right child\u2019s left subtree?' }] },
      { replies:[
          { text:'The right child becomes the root', bot:'Yes. One gap left: the right child already had a left subtree. Where does it go?' },
          { text:'I\u2019m not sure', bot:'Then we found the real gap. The right child rises to root. Say that back to me and keep going.' }] },
      { replies:[
          { text:'It reattaches as the old root\u2019s right child', bot:'That is the complete explanation, and you got there yourself. Gaps closed: 2 of 2. Mastery on AVL rotations moved 24% \u2192 52%, higher than reading would have earned.' },
          { text:'It gets discarded', bot:'It cannot be, that would lose keys. Every value in it sits between the old root and the new one, so it becomes the old root\u2019s right child. Worth re-explaining once more.' }] },
    ],
  },
};
