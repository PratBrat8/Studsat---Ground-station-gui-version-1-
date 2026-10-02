import React, { useMemo } from 'react';

/**
 * Raw frame hex — grouped 8 bytes per line (PRD C.5).
 * @param {{ hex: string, bytesPerLine?: number, highlightCrc?: boolean }} props
 */
export default function HexView({
  hex = '',
  bytesPerLine = 8,
  highlightCrc = false,
  mode = 'at',
  emptyLabel = 'No frame selected',
}) {
  const lines = useMemo(() => {
    if (!hex || typeof hex !== 'string') return [];
    const bytes = hex.trim().split(/\s+/).filter(Boolean);
    if (bytes.length === 0) return [];

    const out = [];
    for (let i = 0; i < bytes.length; i += bytesPerLine) {
      const slice = bytes.slice(i, i + bytesPerLine);
      const isLast = i + bytesPerLine >= bytes.length;
      out.push({
        offset: i,
        bytes: slice,
        // Last 2 bytes of full frame are CRC (when we show full raw_bytes)
        crcStart:
          highlightCrc && isLast
            ? Math.max(0, slice.length - (bytes.length >= 2 ? 2 : 0))
            : -1,
      });
    }
    // Mark CRC on the actual last two bytes across lines
    if (highlightCrc && bytes.length >= 2) {
      const crcIdx0 = bytes.length - 2;
      const crcIdx1 = bytes.length - 1;
      return out.map((line) => ({
        ...line,
        bytes: line.bytes.map((b, j) => {
          const abs = line.offset + j;
          return {
            b,
            isCrc: abs === crcIdx0 || abs === crcIdx1,
            isSync: abs === 0 || abs === 1,
            isHeader: abs >= 2 && abs <= 5,
          };
        }),
      }));
    }
    return out.map((line) => ({
      ...line,
      bytes: line.bytes.map((b) => ({ b, isCrc: false, isSync: false, isHeader: false })),
    }));
  }, [hex, bytesPerLine, highlightCrc]);

  if (lines.length === 0) {
    return <div className="hex-view empty muted small">{emptyLabel}</div>;
  }

  return (
    <div className="hex-view" role="region" aria-label="Raw hex frame">
      <pre className="hex-pre">
        {lines.map((line) => (
          <div key={line.offset} className="hex-line">
            <span className="hex-offset">
              {line.offset.toString(16).padStart(4, '0')}
            </span>
            <span className="hex-bytes">
              {line.bytes.map((cell, j) => (
                <span
                  key={`${line.offset}-${j}`}
                  className={[
                    'hex-byte',
                    cell.isSync ? 'sync' : '',
                    cell.isHeader ? 'header' : '',
                    cell.isCrc ? 'crc' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                >
                  {cell.b}
                </span>
              ))}
            </span>
            <span className="hex-ascii">
              {line.bytes
                .map((cell) => {
                  const n = parseInt(cell.b, 16);
                  if (Number.isNaN(n)) return '.';
                  return n >= 32 && n < 127 ? String.fromCharCode(n) : '.';
                })
                .join('')}
            </span>
          </div>
        ))}
      </pre>
      {mode === 'at' ? (
        <div className="hex-legend muted small">
          Reyax AT ASCII · +RCV=&lt;addr&gt;,&lt;len&gt;,&lt;data&gt;,&lt;rssi&gt;,&lt;snr&gt;
        </div>
      ) : (
        <div className="hex-legend muted small">
          <span className="hex-byte sync">AA 55</span> sync{' '}
          <span className="hex-byte header">hdr</span> vehicle/type/seq/len{' '}
          <span className="hex-byte crc">CRC16</span>
        </div>
      )}
    </div>
  );
}
