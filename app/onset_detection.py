"""Finding the moment something was struck, rather than the moment it got loud.

The detector this sits beside asks one question: is the bass a bigger share of
the block than it recently was? That is cheap and it works on most tracks,
because a kick is the loudest thing in the low band. It also has no way of
telling a drum from a voice that happens to be low, so a sung syllable, a
plosive, or a bass guitar with no drums behind it can all read as a strike.

This is the other question: has energy *appeared* that was not there a moment
ago? A sustained note — even a loud one, even one being pushed around by
vibrato — is energy that was already there. A struck drum is not.

The method is the one described as SuperFlux (Böck & Widmer, DAFx-13). Two parts
matter and both are small:

**Compare with a maximum, not with the previous value.** A voice with vibrato
moves its harmonics a little from block to block, and a plain difference reads
every one of those movements as new energy. Taking the maximum of the previous
block over neighbouring bins means a harmonic that merely slid sideways is still
covered by where it used to be, and contributes nothing.

**Ask where the new energy is.** Turning the volume up raises everything at
once, which is a large flux and not a beat. A strike puts its new energy in the
low band, so the low band's share of the new energy has to rise too — the same
reasoning as the share test the old detector uses, applied to what appeared
rather than to what is there.

Nothing here separates a voice from a drum. A hard syllable from a low male
voice still looks like a strike, and no amount of spectral arithmetic changes
that without knowing what a voice is. What it does remove is the sustained
singing, the vibrato and the slow swells, which is most of what was false.

**How coarse this really is.** At 1024 samples and 48 kHz a bin is 46.9 Hz
wide, so the 35-120 Hz band is *two bins* — 46.9 and 93.8. The published method
works on a far more detailed frequency representation, with the maximum filter
applied across many narrow bands; this borrows the two ideas that carry most of
the benefit and applies them to what the capture already computes. It is a study
of whether the approach helps here, not an accurate separation of a kick from a
low male voice, and the numbers it reports should be read that way.

Pure: numpy in, numbers out, no audio device and no Qt, so a vibrato that would
take four seconds to sing can be played through it in a millisecond.
"""

from __future__ import annotations

from dataclasses import dataclass

# Neighbouring bins the previous block is maximised over. Three is one bin
# either side: enough to cover the wobble of a sung note at this resolution
# (47 Hz per bin at 1024/48k), few enough that a real strike still stands out
# against it.
MAX_FILTER_BINS = 3

# Where a struck drum puts its energy. Narrower than the 20-250 Hz the old
# detector uses, and narrower than it first looked right: a kick's fundamental
# lives around 40-90 Hz, while a male voice sits at 85-180 and a female one
# higher still. A band that reaches to 200 Hz is a band that contains most
# singing, which is the thing being separated from.
LOW_HZ = (35.0, 120.0)

# The bar a block has to clear, as a fraction of how far the recent window
# spreads. Written as mean + δ·(max − mean) rather than as a multiple of the
# mean, because a multiple degenerates: over a passage with nothing in the low
# band the mean is zero and everything is "twice" it. Scale-free either way, so
# a quiet track and a loud one are judged the same.
PEAK_DELTA = 0.55
# How far back "recently" reaches, in blocks. About half a second at 1024/48k:
# long enough to describe the passage, short enough to follow a change of
# section rather than average two of them together.
HISTORY_BLOCKS = 22
# How many blocks a strike has to be the largest of. A drum's energy arrives in
# one block and is gone; a swell rises across many, and is never the peak of its
# own neighbourhood.
LOCAL_MAX_BLOCKS = 3
# And most of what appeared has to be down there. Turning the volume up raises
# every bin at once — a great deal of new energy, spread everywhere — so this is
# what separates a louder passage from a struck drum.
LOW_CONCENTRATION = 0.15
# And it has to be audible: at least this share of everything in the block.
# Without it the bar is purely relative, and over a passage with nothing in the
# low band a numerical whisper clears it — the leakage of a sung note wobbling
# below its own fundamental was firing on a low flux of 0.1 where a struck drum
# gives 1.15. Measured on synthetic voice and drums the two sit 16x apart, so
# this is a floor rather than a knife edge.
LOW_ENERGY_FLOOR = 0.02
# Below this there is no signal to speak of and every ratio is noise.
_MIN_FLUX = 1e-4

# The shortest gap between two strikes, in milliseconds. The same reasoning as
# the old detector's: fast enough for 200 bpm, slow enough that one kick is not
# counted three times.
MIN_ONSET_GAP_MS = 110.0


@dataclass(frozen=True)
class OnsetReading:
    """What one block looked like to this detector."""

    onset: bool = False
    # Energy that appeared since the previous block, after the maximum filter.
    flux: float = 0.0
    # The part of it in the low band, and that part as a share of the whole.
    low_flux: float = 0.0
    low_share: float = 0.0


@dataclass
class OnsetStats:
    """Counters for the diagnostics block. No audio, no device names."""

    blocks: int = 0
    onsets: int = 0


def _max_filtered(values, bins: int):
    """Each bin replaced by the largest of itself and its neighbours.

    Written with shifted slices rather than a filter from scipy: it is three
    lines, it is the only thing that would have been imported, and adding a
    dependency of that size for it would be the wrong trade.
    """
    import numpy as np

    if bins <= 1 or values.size == 0:
        return values
    reach = bins // 2
    padded = np.pad(values, reach, mode="edge")
    out = padded[reach : reach + values.size].copy()
    for shift in range(1, reach + 1):
        out = np.maximum(out, padded[reach - shift : reach - shift + values.size])
        out = np.maximum(out, padded[reach + shift : reach + shift + values.size])
    return out


class SuperFluxOnset:
    """One source's idea of when something was struck.

    Fed the magnitude spectrum of each block, in order. Holds the previous
    spectrum and a running idea of what a normal amount of new energy looks
    like — nothing else, and no audio.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._previous = None
        self._history: list[float] = []
        self._recent: list[float] = []
        self._last_onset_ms: float | None = None
        self.stats = OnsetStats()

    def feed(self, magnitudes, freqs, now_ms: float) -> OnsetReading:
        """Judge one block. ``magnitudes`` and ``freqs`` come from one rfft."""
        import numpy as np

        self.stats.blocks += 1
        spectrum = np.log1p(np.asarray(magnitudes, dtype=np.float32))
        previous = self._previous
        self._previous = spectrum
        if previous is None or previous.size != spectrum.size:
            return OnsetReading()

        # Only what appeared. A harmonic that slid a bin sideways is still
        # covered by where it was, so vibrato contributes nothing.
        appeared = np.maximum(0.0, spectrum - _max_filtered(previous, MAX_FILTER_BINS))
        flux = float(appeared.sum())
        low_mask = (freqs >= LOW_HZ[0]) & (freqs <= LOW_HZ[1])
        low_flux = float(appeared[low_mask].sum())
        low_share = low_flux / flux if flux > _MIN_FLUX else 0.0

        onset = self._decide(low_flux, low_share, float(spectrum.sum()), now_ms)
        # The window follows whatever the block turned out to be, so a passage
        # of steady playing becomes the new normal rather than a strike on every
        # block. Appended after the decision: a block must not raise the bar it
        # is being judged by.
        self._history.append(low_flux)
        if len(self._history) > HISTORY_BLOCKS:
            del self._history[:-HISTORY_BLOCKS]
        self._recent.append(low_flux)
        if len(self._recent) > LOCAL_MAX_BLOCKS:
            del self._recent[:-LOCAL_MAX_BLOCKS]
        if onset:
            self.stats.onsets += 1
            self._last_onset_ms = now_ms
        return OnsetReading(
            onset=onset, flux=flux, low_flux=low_flux, low_share=low_share
        )

    def _decide(self, low_flux: float, low_share: float, energy: float, now_ms: float) -> bool:
        """Causal peak picking: a local maximum, clearly above the recent spread.

        The shape is the usual one — local maximum, mean plus a margin, minimum
        gap — with one addition of its own: where the new energy landed.
        """
        # Silence has no onsets, and every ratio below it would be noise over
        # noise. Nothing else is vetoed for want of history: sound beginning
        # after quiet *is* a strike, and refusing it until a window had filled
        # meant the first beat of every track went unheard.
        if low_flux <= _MIN_FLUX:
            return False
        if self._last_onset_ms is not None and (now_ms - self._last_onset_ms) < MIN_ONSET_GAP_MS:
            return False
        # A louder passage raises every bin at once, so most of its new energy is
        # not down here; a strike's is.
        if low_share < LOW_CONCENTRATION:
            return False
        if energy > 0.0 and low_flux < energy * LOW_ENERGY_FLOOR:
            # Real, but too small to be a drum in this mix.
            return False
        if self._recent and low_flux < max(self._recent):
            # A swell rises across many blocks and is never the peak of its own
            # neighbourhood. A drum arrives in one and is gone.
            return False
        if not self._history:
            return True
        mean = sum(self._history) / len(self._history)
        spread = max(self._history) - mean
        return low_flux > mean + PEAK_DELTA * spread + _MIN_FLUX


@dataclass(frozen=True)
class OnsetComparison:
    """How the two detectors agreed over a run, for the diagnostics block."""

    old_beats: int = 0
    shadow_candidates: int = 0
    matched: int = 0
    shadow_only: int = 0
    old_only: int = 0


class OnsetAgreement:
    """Pairs up what the two detectors heard, one strike to one strike.

    Counting agreement as "both fired in the same block" is wrong here, because
    the two do not have to land in the same block: this detector reads the onset
    from the change *into* a block and the old one from the block's own content,
    so the same drum can be a block apart in the two. Counted strictly, that one
    strike becomes a miss and an extra — two errors invented from one agreement.

    So events are matched within a tolerance, and matched *once*: an old beat
    that has already confirmed a candidate cannot confirm the next one too, or
    a detector that fires twice as often would look twice as accurate.

    Nothing here keeps audio, and the waiting lists hold a handful of timestamps
    at most — an event that has waited longer than the tolerance can never find
    a partner, so it is settled and dropped.
    """

    def __init__(self, *, tolerance_ms: float = 25.0, max_waiting: int = 8) -> None:
        self._tolerance_ms = float(tolerance_ms)
        self._max_waiting = int(max_waiting)
        self.reset()

    def reset(self) -> None:
        self._waiting_old: list[float] = []
        self._waiting_shadow: list[float] = []
        self._old_beats = 0
        self._shadow_candidates = 0
        self._matched = 0
        self._old_only = 0
        self._shadow_only = 0

    def set_tolerance_ms(self, tolerance_ms: float) -> None:
        """One audio block, whatever the device's block turns out to be."""
        self._tolerance_ms = max(1.0, float(tolerance_ms))

    def note(self, *, old: bool, shadow: bool, now_ms: float) -> None:
        """Record what each detector said about one block."""
        self._settle(now_ms)
        if old and shadow:
            # The same block: no search needed, and no chance of either being
            # paired with something else first.
            self._old_beats += 1
            self._shadow_candidates += 1
            self._matched += 1
            return
        if old:
            self._old_beats += 1
            if not self._take(self._waiting_shadow):
                self._park(self._waiting_old, now_ms)
        if shadow:
            self._shadow_candidates += 1
            if not self._take(self._waiting_old):
                self._park(self._waiting_shadow, now_ms)

    def _take(self, waiting: list[float]) -> bool:
        """Pair with the oldest event waiting, and use it up.

        Everything past its tolerance has already been settled by ``_settle`` at
        the top of ``note``, so whatever is still here is close enough. Checking
        again would read as caution and be unreachable — a line that can never
        run is a line nobody can trust.
        """
        if not waiting:
            return False
        waiting.pop(0)
        self._matched += 1
        return True

    def _park(self, waiting: list[float], now_ms: float) -> None:
        if len(waiting) >= self._max_waiting:
            # Cannot happen with a tolerance of one block and events this rare,
            # but a list on the audio path is not left to grow on a promise.
            self._settle_one(waiting.pop(0), waiting)
        waiting.append(now_ms)

    def _settle(self, now_ms: float) -> None:
        for waiting in (self._waiting_old, self._waiting_shadow):
            while waiting and now_ms - waiting[0] > self._tolerance_ms:
                self._settle_one(waiting.pop(0), waiting)

    def _settle_one(self, _when: float, waiting: list[float]) -> None:
        if waiting is self._waiting_old:
            self._old_only += 1
        else:
            self._shadow_only += 1

    def totals(self, now_ms: float) -> OnsetComparison:
        """The comparison so far, with everything past its chance settled."""
        self._settle(now_ms)
        return OnsetComparison(
            old_beats=self._old_beats,
            shadow_candidates=self._shadow_candidates,
            matched=self._matched,
            shadow_only=self._shadow_only + len(self._waiting_shadow),
            old_only=self._old_only + len(self._waiting_old),
        )
