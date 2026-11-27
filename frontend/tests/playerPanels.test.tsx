/**
 * Copyright (c) 2026 tbaur
 *
 * Licensed under the Apache License, Version 2.0
 * See LICENSE file for full license text
 *
 * The three panels of the player page: now playing and transport, device
 * metrics, and Advanced (queue, inputs, presets, Bluetooth, maintenance).
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { PlayerStatus, QueueResponse, UpgradeStatus } from '@/api/types';
import { AdvancedPanel } from '@/components/player/AdvancedPanel';
import { DeviceMetricsPanel } from '@/components/player/DeviceMetricsPanel';
import { NowPlayingPanel } from '@/components/player/NowPlayingPanel';
import { byTextContent } from './textContent';

const api = vi.hoisted(() => ({
  back: vi.fn(),
  toggle: vi.fn(),
  stop: vi.fn(),
  skip: vi.fn(),
  seek: vi.fn(),
  clearQueue: vi.fn(),
  getQueue: vi.fn(),
  setInput: vi.fn(),
  getInputs: vi.fn(),
  playPreset: vi.fn(),
  setBluetooth: vi.fn(),
  getBluetooth: vi.fn(),
  getUpgrade: vi.fn(),
  reboot: vi.fn(),
}));

vi.mock('@/api/client', () => ({ api }));

vi.mock('@/components/DeviceSettingsPanel', () => ({
  DeviceSettingsPanel: () => <div data-testid="settings-panel" />,
}));

const device: PlayerStatus = {
  id: 'player-1',
  ip: '192.168.1.20',
  name: 'Zone One',
  model: 'NODE',
  brand: 'Bluesound',
  full_model: 'Bluesound NODE',
  device_class: 'streamer',
  mac: '02:00:00:00:00:01',
  status: 'online',
  state: 'play',
  service: 'TIDAL',
  service_id: '',
  volume: 25,
  muted: false,
  db: '-35',
  fw: '4.16.6',
  master: '',
  group: '',
  group_volume: null,
  slaves: [],
  sync_role: 'standalone',
  battery: null,
  track: 'Song',
  artist: 'Artist',
  album: 'Album',
  quality: 'cd',
  stream_format: 'FLAC 16/44.1',
  image: '',
  secs: 10,
  totlen: 200,
  can_seek: true,
  input_type_index: '',
  consecutive_failures: 0,
  last_seen: 1,
};

/** Runs the control at once, like the page does, so the api calls can be checked. */
function runner() {
  return vi.fn((action: () => Promise<unknown>) => {
    void action();
  });
}

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('NowPlayingPanel', () => {
  it('shows the track and sends each transport command with its paint', () => {
    const onControl = runner();
    render(<NowPlayingPanel device={device} activeInputName={null} onControl={onControl} />);
    expect(screen.getByRole('heading', { name: 'Song' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
    expect(onControl).toHaveBeenLastCalledWith(expect.any(Function), { state: 'pause' });
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    expect(onControl).toHaveBeenLastCalledWith(expect.any(Function), { state: 'stop' });
    fireEvent.click(screen.getByRole('button', { name: 'Prev' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(api.toggle).toHaveBeenCalledWith('player-1');
    expect(api.stop).toHaveBeenCalledWith('player-1');
    expect(api.back).toHaveBeenCalledWith('player-1');
    expect(api.skip).toHaveBeenCalledWith('player-1');
  });

  it.each([
    [{ track: '', state: 'stop' }, 'Idle'],
    [{ track: '', state: 'pause' }, 'Paused'],
    [{ track: '', state: 'stream' }, 'Playing'],
    [{ track: '', state: 'buffering' }, 'buffering'],
  ] as const)('titles a player with %o as %s', (patch, title) => {
    render(
      <NowPlayingPanel
        device={{ ...device, ...patch }}
        activeInputName="Optical"
        onControl={vi.fn()}
      />,
    );
    expect(screen.getByRole('heading', { name: title })).toBeInTheDocument();
  });

  it('turns off Prev and Next for a station that offers neither', () => {
    render(
      <NowPlayingPanel
        device={{ ...device, live: true, can_skip: false, can_back: false, totlen: 0 }}
        activeInputName={null}
        onControl={vi.fn()}
      />,
    );
    expect(screen.getByRole('button', { name: 'Prev' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('shows Play for a paused player', () => {
    const onControl = runner();
    render(
      <NowPlayingPanel
        device={{ ...device, state: 'pause' }}
        activeInputName={null}
        onControl={onControl}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    expect(onControl).toHaveBeenLastCalledWith(expect.any(Function), { state: 'play' });
  });
});

function metrics(overrides: Partial<Parameters<typeof DeviceMetricsPanel>[0]> = {}) {
  const props = {
    device,
    role: 'standalone',
    primaryName: null,
    diag: null,
    upgrade: null,
    health: null,
    activeInputName: null,
    onVolume: vi.fn(),
    onToggleMute: vi.fn(),
    ...overrides,
  };
  render(<DeviceMetricsPanel {...props} />);
  return props;
}

const upgrade = (patch: Partial<UpgradeStatus>): UpgradeStatus => ({
  device_id: 'player-1',
  name: 'Zone One',
  ip: '192.168.1.20',
  current_fw: '4.16.6',
  update_available: false,
  message: '',
  ok: true,
  ...patch,
});

describe('DeviceMetricsPanel', () => {
  it.each([
    [{ role: 'primary', device: { ...device, group: 'Downstairs' } }, 'Leading Downstairs'],
    [{ role: 'primary', device: { ...device, slaves: ['a', 'b'] } }, 'Leading 2 followers'],
    [{ role: 'primary' }, 'Leading group'],
    [{ role: 'synced', primaryName: 'Zone Two' }, 'Following Zone Two'],
    [{ role: 'synced', device: { ...device, group: 'Upstairs' } }, 'In Upstairs'],
    [{ role: 'synced' }, 'Following group'],
    [{}, 'Standalone'],
  ])('summarises sync as %s', (overrides, text) => {
    metrics(overrides);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it.each([
    [upgrade({ ok: false }), 'check failed'],
    [upgrade({ update_available: true }), 'update available'],
    [upgrade({}), 'up to date'],
  ])('labels firmware %#', (status, label) => {
    metrics({ upgrade: status });
    expect(screen.getByText(byTextContent(new RegExp(`4\\.16\\.6.*${label}`)))).toBeInTheDocument();
  });

  it('shows diagnostics, battery, and the capture input when the player has them', () => {
    metrics({
      device: { ...device, battery: '80', input_type_index: 'spdif', muted: true },
      activeInputName: 'Optical',
      diag: {
        device_id: 'player-1',
        ip: '192.168.1.20',
        port: 11000,
        name: 'Zone One',
        model: '',
        full_model: '',
        device_class: '',
        mac: '',
        fw: '',
        state: '',
        service: '',
        volume: 0,
        muted: false,
        db: '',
        sync_role: 'standalone',
        master: '',
        group: '',
        quality: '',
        stream_format: '',
        uptime: '2d 3h',
        network_name: 'Home Wi-Fi',
        signal_strength: '-60 dBm',
        total_songs: '1200',
        web_ip: null,
        web_mac: null,
        web_fw: null,
      },
    });
    expect(screen.getByText('-60 dBm')).toBeInTheDocument();
    expect(screen.getByText('1200')).toBeInTheDocument();
    expect(screen.getByText('80%')).toBeInTheDocument();
    expect(screen.getByText('Optical')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unmute' })).toBeInTheDocument();
  });

  it('sends slider moves and the mute toggle', () => {
    const props = metrics();
    fireEvent.change(screen.getByLabelText('Device volume'), { target: { value: '40' } });
    expect(props.onVolume).toHaveBeenCalledWith(40);
    fireEvent.click(screen.getByRole('button', { name: 'Mute' }));
    expect(props.onToggleMute).toHaveBeenCalled();
  });

  it('marks slow-poll once failures reach the threshold', () => {
    metrics({
      device: { ...device, consecutive_failures: 6 },
      health: {
        started_at: 0,
        observed_at: 10,
        window_seconds: 86_400,
        presence_window_seconds: 43_200,
        circuit_failure_threshold: 5,
        first_online: { 'player-1': 0 },
        drops: [],
      },
    });
    expect(screen.getByText(byTextContent(/^6.*slow-poll$/))).toBeInTheDocument();
  });
});

function advanced(overrides: Partial<Parameters<typeof AdvancedPanel>[0]> = {}) {
  const queue: QueueResponse = {
    items: [
      { title: 'One', artist: 'A', album: '', image: '', service: '' },
      { title: 'Two', artist: 'B', album: '', image: '', service: '' },
    ],
    count: 2,
  };
  const props = {
    device,
    open: true,
    onOpenChange: vi.fn(),
    queue,
    setQueue: vi.fn(),
    onMoveQueue: vi.fn(),
    inputs: [
      { name: 'Optical', type: 'spdif', id: 'spdif-1', selected: false },
      { name: 'Analog', type: 'analog', id: '', selected: true },
    ],
    setInputs: vi.fn(),
    presets: [{ id: '3', name: '', image: '' }],
    loaded: true,
    bluetooth: { supported: true, mode: 'Automatic' },
    applyBluetooth: vi.fn(),
    upgrade: null,
    setUpgrade: vi.fn(),
    onControl: runner(),
    ...overrides,
  };
  render(<AdvancedPanel {...props} />);
  return props;
}

describe('AdvancedPanel', () => {
  it('moves queue items and clears the queue after confirming', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    api.getQueue.mockResolvedValue({ items: [], count: 0 });
    const props = advanced();
    fireEvent.click(screen.getByRole('button', { name: 'Move One down' }));
    expect(props.onMoveQueue).toHaveBeenCalledWith(0, 1);
    fireEvent.click(screen.getByRole('button', { name: 'Move Two up' }));
    expect(props.onMoveQueue).toHaveBeenCalledWith(1, 0);
    fireEvent.click(screen.getByRole('button', { name: 'Clear queue' }));
    await waitFor(() => {
      expect(props.setQueue).toHaveBeenCalledWith({ items: [], count: 0 });
    });
    expect(api.clearQueue).toHaveBeenCalledWith('player-1');
  });

  it('says how much of a long queue it shows', () => {
    advanced({
      queue: {
        items: [{ title: 'One', artist: '', album: '', image: '', service: '' }],
        count: 900,
      },
    });
    expect(screen.getByText('Showing the first 1 of 900 tracks.')).toBeInTheDocument();
  });

  it('selects an input, plays a preset, and sets a Bluetooth mode', async () => {
    api.getInputs.mockResolvedValue([]);
    api.getBluetooth.mockResolvedValue({ supported: true, mode: 'Guest' });
    const props = advanced();
    fireEvent.click(screen.getByRole('button', { name: 'Select' }));
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    fireEvent.click(screen.getByRole('button', { name: 'Guest' }));
    await waitFor(() => {
      expect(props.applyBluetooth).toHaveBeenCalledWith({ supported: true, mode: 'Guest' });
    });
    expect(api.setInput).toHaveBeenCalledWith('player-1', 'spdif-1');
    expect(props.setInputs).toHaveBeenCalledWith([]);
    expect(api.playPreset).toHaveBeenCalledWith('player-1', '3');
    expect(api.setBluetooth).toHaveBeenCalledWith('player-1', 2);
    expect(screen.getByText('Preset 3')).toBeInTheDocument();
  });

  it('checks for an upgrade, and reports a failed check', async () => {
    api.getUpgrade.mockRejectedValue(new Error('down'));
    const props = advanced({ upgrade: upgrade({ update_available: true }) });
    expect(screen.getByText(/An update is available/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Check for upgrade' }));
    await waitFor(() => {
      expect(props.setUpgrade).toHaveBeenCalledWith(expect.objectContaining({ ok: false }));
    });
  });

  it('reboots only after confirming', () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    advanced();
    fireEvent.click(screen.getByRole('button', { name: 'Reboot' }));
    expect(api.reboot).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: 'Reboot' }));
    expect(api.reboot).toHaveBeenCalledWith('player-1');
  });

  it('hides Bluetooth and the settings when they do not apply', () => {
    advanced({ open: false, bluetooth: { supported: false, mode: '' }, presets: [] });
    expect(screen.queryByRole('heading', { name: 'Bluetooth' })).not.toBeInTheDocument();
    expect(screen.queryByTestId('settings-panel')).not.toBeInTheDocument();
    expect(screen.getByText('No presets')).toBeInTheDocument();
  });
});
