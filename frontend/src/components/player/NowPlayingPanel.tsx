/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * Now playing on the player page: art, title, quality, seek, and transport.
 */

import { api } from '@/api/client';
import type { PlayerStatus } from '@/api/types';
import { MetaText } from '@/components/MetaText';
import { SeekBar } from '@/components/SeekBar';
import { StickyArt } from '@/components/StickyArt';
import { playerArtSrc } from '@/lib/artwork';
import { artistAlbumLines, joinMeta } from '@/lib/meta';
import { NO_BACK, NO_SKIP, canBack, canSkip } from '@/lib/stationActions';
import { showsPlaybackBar } from '@/lib/playbackClock';
import { streamQualityLabel } from '@/lib/streamQuality';

export type RunControl = (action: () => Promise<void>, optimistic?: Partial<PlayerStatus>) => void;

function isActive(state: string): boolean {
  return ['play', 'stream', 'connecting'].includes(state);
}

function isIdle(device: PlayerStatus): boolean {
  return (
    !device.track.trim() &&
    (device.state === 'stop' || device.state === '' || device.state === 'pause')
  );
}

function nowTitle(device: PlayerStatus): string {
  if (device.track.trim()) return device.track;
  if (device.state === 'pause') return 'Paused';
  if (isIdle(device)) return 'Idle';
  if (isActive(device.state)) return 'Playing';
  return device.state || 'Idle';
}

interface NowPlayingPanelProps {
  device: PlayerStatus;
  activeInputName: string | null;
  onControl: RunControl;
}

export function NowPlayingPanel({ device, activeInputName, onControl }: NowPlayingPanelProps) {
  const idle = isIdle(device);
  const metaLine = streamQualityLabel(device);
  const lines = artistAlbumLines(device.track, device.artist, device.album);
  return (
    <section className="panel dossier-now">
      <div className="dossier-now-grid">
        <div className="dossier-art" aria-hidden={!device.image}>
          <StickyArt
            src={playerArtSrc(device.id, device.image)}
            empty={<div className="dossier-art-empty">No artwork</div>}
          />
        </div>
        <div className="dossier-now-copy">
          {idle ? <p className="card-meta">Status</p> : null}
          <h2>{nowTitle(device)}</h2>
          {!idle && (
            <>
              <p className="dossier-now-meta">{lines.artist || '—'}</p>
              {lines.album ? (
                <p className="dossier-now-meta dossier-now-album">{lines.album}</p>
              ) : null}
            </>
          )}
          <p className="card-meta">
            <MetaText
              text={joinMeta(
                device.service || null,
                activeInputName ? `Input ${activeInputName}` : null,
                !idle ? metaLine || null : null,
                !idle ? device.state : null,
              )}
            />
          </p>
          {showsPlaybackBar(device) && (
            <SeekBar
              key={device.id}
              initialSecs={device.secs}
              totlen={device.totlen}
              playing={['play', 'stream'].includes(device.state)}
              canSeek={device.can_seek}
              onSeek={
                device.can_seek
                  ? (seconds) => onControl(() => api.seek(device.id, seconds), { secs: seconds })
                  : undefined
              }
            />
          )}
          <Transport device={device} onControl={onControl} />
        </div>
      </div>
    </section>
  );
}

function Transport({ device, onControl }: { device: PlayerStatus; onControl: RunControl }) {
  const playing = isActive(device.state);
  return (
    <div className="transport" style={{ marginTop: 14 }}>
      <button
        type="button"
        className="btn"
        disabled={!canBack(device)}
        title={canBack(device) ? undefined : NO_BACK}
        onClick={() => onControl(() => api.back(device.id))}
      >
        Prev
      </button>
      <button
        type="button"
        className="btn btn-primary"
        onClick={() =>
          onControl(() => api.toggle(device.id), { state: playing ? 'pause' : 'play' })
        }
      >
        {playing ? 'Pause' : 'Play'}
      </button>
      <button
        type="button"
        className="btn"
        onClick={() => onControl(() => api.stop(device.id), { state: 'stop' })}
      >
        Stop
      </button>
      <button
        type="button"
        className="btn"
        disabled={!canSkip(device)}
        title={canSkip(device) ? undefined : NO_SKIP}
        onClick={() => onControl(() => api.skip(device.id))}
      >
        Next
      </button>
    </div>
  );
}
