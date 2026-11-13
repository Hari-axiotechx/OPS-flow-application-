/**
 * Auto-generated cartoon avatar.
 *
 * Every user gets a little cartoon face instead of an uploaded photo.
 * It's deterministic: the same seed (we use the user's id, falling
 * back to email/name) always produces the same face, so a person
 * doesn't get a different avatar on every page load — but two
 * different users almost always look different.
 */

const BG_COLORS = [
  '#2563EB', '#7C3AED', '#DB2777', '#DC2626', '#EA580C',
  '#D97706', '#65A30D', '#059669', '#0891B2', '#4F46E5',
];

const FACE_COLORS = ['#FFDAB3', '#F5C39A', '#E7A978', '#C48A5F', '#8D5A3C'];
const HAIR_COLORS = ['#2B2118', '#4A3323', '#6B4226', '#1F1F1F', '#8C5B2E', 'none'];

function hashString(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (h << 5) - h + str.charCodeAt(i);
    h |= 0;
  }
  return Math.abs(h) || 1;
}

// Small deterministic PRNG (mulberry32) seeded from the hash above, so
// every "random" choice below is stable per seed instead of per render.
function mulberry32(seed) {
  let a = seed;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick(rand, arr) {
  return arr[Math.floor(rand() * arr.length)];
}

export default function Avatar({ seed, name = '', size = 40, className = '' }) {
  const rand = mulberry32(hashString(String(seed || name || 'user')));

  const bg = pick(rand, BG_COLORS);
  const skin = pick(rand, FACE_COLORS);
  const hair = pick(rand, HAIR_COLORS);
  const eyeStyle = Math.floor(rand() * 3);
  const mouthStyle = Math.floor(rand() * 3);
  const hasCheeks = rand() > 0.55;
  const hasGlasses = rand() > 0.78;

  return (
    <span
      className={`inline-flex items-center justify-center rounded-full overflow-hidden flex-shrink-0 ${className}`}
      style={{ width: size, height: size, backgroundColor: bg }}
    >
      <svg
        viewBox="0 0 100 100"
        width="100%"
        height="100%"
        role="img"
        aria-label={name ? `${name}'s avatar` : 'User avatar'}
      >
        {/* Face */}
        <circle cx="50" cy="54" r="30" fill={skin} />

        {/* Hair */}
        {hair !== 'none' && (
          <path
            d="M20 46 A30 30 0 0 1 80 46 C80 30 68 18 50 18 C32 18 20 30 20 46 Z"
            fill={hair}
          />
        )}

        {/* Eyes */}
        {eyeStyle === 0 && (
          <>
            <circle cx="39" cy="52" r="4" fill="#1F2937" />
            <circle cx="61" cy="52" r="4" fill="#1F2937" />
          </>
        )}
        {eyeStyle === 1 && (
          <>
            <ellipse cx="39" cy="52" rx="3.5" ry="5.5" fill="#1F2937" />
            <ellipse cx="61" cy="52" rx="3.5" ry="5.5" fill="#1F2937" />
          </>
        )}
        {eyeStyle === 2 && (
          <>
            <path d="M34 52 Q39 47 44 52" stroke="#1F2937" strokeWidth="2.5" fill="none" strokeLinecap="round" />
            <path d="M56 52 Q61 47 66 52" stroke="#1F2937" strokeWidth="2.5" fill="none" strokeLinecap="round" />
          </>
        )}

        {/* Cheeks */}
        {hasCheeks && (
          <>
            <circle cx="28" cy="63" r="5.5" fill="#FF9AA2" opacity="0.5" />
            <circle cx="72" cy="63" r="5.5" fill="#FF9AA2" opacity="0.5" />
          </>
        )}

        {/* Mouth */}
        {mouthStyle === 0 && (
          <path d="M38 68 Q50 79 62 68" stroke="#1F2937" strokeWidth="3" fill="none" strokeLinecap="round" />
        )}
        {mouthStyle === 1 && (
          <ellipse cx="50" cy="71" rx="7" ry="5" fill="#7A3B2E" />
        )}
        {mouthStyle === 2 && (
          <path d="M42 70 L58 70" stroke="#1F2937" strokeWidth="3" strokeLinecap="round" />
        )}

        {/* Glasses */}
        {hasGlasses && (
          <g stroke="#1F2937" strokeWidth="2.5" fill="none">
            <rect x="30" y="46" width="18" height="13" rx="4" />
            <rect x="52" y="46" width="18" height="13" rx="4" />
            <path d="M48 51 L52 51" />
          </g>
        )}
      </svg>
    </span>
  );
}
