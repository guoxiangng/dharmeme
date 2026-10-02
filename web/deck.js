// The order Random shows the pool in (SPEC.md §4a). Keep in step with feedback.py.
//
// Every meme appears exactly once per pass, however it is rated, so exposure stays even
// and a well-liked meme cannot crowd out the rest. Votes only nudge the order within a
// pass: by up-rate, not by count, and only once a meme has MIN_VOTES votes.

export const MIN_VOTES = 10; // below this a meme counts as unrated
const NUDGE = 0.5; // how far a rating can shift a meme within the shuffle (0 = pure shuffle)

// Share of thumbs up, or null while there are too few votes to say.
export function upRate(meme) {
  const total = (meme.up || 0) + (meme.down || 0);
  return total >= MIN_VOTES ? (meme.up || 0) / total : null;
}

// One pass of the pool, as a stack: pop() gives the next meme to show.
export function deck(memes, random = Math.random) {
  const keyed = memes.map((meme) => {
    const rate = upRate(meme);
    return { meme, key: random() + (rate === null ? 0 : NUDGE * (rate - 0.5)) };
  });
  keyed.sort((a, b) => a.key - b.key);
  return keyed.map((k) => k.meme);
}
