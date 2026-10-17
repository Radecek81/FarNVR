// Browser codec capability checks shared by live and playback views.

export function hevcSupported() {
  const MS = window.ManagedMediaSource || window.MediaSource;
  try {
    return !!MS && (MS.isTypeSupported('video/mp4; codecs="hvc1.1.6.L120.90"') ||
      MS.isTypeSupported('video/mp4; codecs="hev1.1.6.L120.90"'));
  } catch (e) { return false; }
}
