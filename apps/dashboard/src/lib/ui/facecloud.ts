/* The face as a cloud of particles, read from face-cloud.bin.

   The file holds one 12-byte record per particle after a 16-byte header:
     header  "TFC1", count (uint32), spacing between neighbours in face units (float32), reserved (uint32)
     record  x, y, z (int16, face units / 4 * 32767)   position; z is toward the viewer
             b, edge, jaw, mouth (uint8, 0..255)        brightness; how loose the particle is (1 = drifting
                                                        around the head); how much it drops with the jaw;
                                                        how close it is to the lips
             nx, ny (int8, -127..127)                   which way the surface faces at this spot
   Face units: x from about -1 (left) to 1 (right), y from -1.2 (top of the head) to 1.2 (chin).
   The records are in a shuffled order, so any first part of the file is an even sample of the whole
   face: a small screen can simply use fewer of them.

   The file is generated from the reference picture by a script kept outside the repository; the renderer
   hands the records to the GPU as they are. */

import cloudUrl from './face-cloud.bin?url';

export const RECORD_BYTES = 12;
const HEADER_BYTES = 16;
const MAGIC = 0x31434654; // "TFC1" read as a little-endian uint32

export interface FaceCloud {
  count: number;
  /** Distance between neighbouring particles, in face units. */
  spacing: number;
  /** `count` records of RECORD_BYTES each. */
  records: Uint8Array;
}

export function parseFaceCloud(buffer: ArrayBuffer): FaceCloud {
  if (buffer.byteLength < HEADER_BYTES) throw new Error('face cloud: file is too short');
  const view = new DataView(buffer);
  if (view.getUint32(0, true) !== MAGIC) throw new Error('face cloud: not a face cloud file');
  const count = view.getUint32(4, true);
  const spacing = view.getFloat32(8, true);
  if (buffer.byteLength !== HEADER_BYTES + count * RECORD_BYTES) throw new Error('face cloud: size does not match its particle count');
  if (!(spacing > 0)) throw new Error('face cloud: bad spacing');
  return { count, spacing, records: new Uint8Array(buffer, HEADER_BYTES, count * RECORD_BYTES) };
}

/** One particle, decoded. The renderer does not need this; it is for tests and tools. */
export function particleAt(cloud: FaceCloud, index: number) {
  const view = new DataView(cloud.records.buffer, cloud.records.byteOffset + index * RECORD_BYTES, RECORD_BYTES);
  const unit = (offset: number) => view.getUint8(offset) / 255;
  return {
    x: (view.getInt16(0, true) / 32767) * 4,
    y: (view.getInt16(2, true) / 32767) * 4,
    z: (view.getInt16(4, true) / 32767) * 4,
    b: unit(6),
    edge: unit(7),
    jaw: unit(8),
    mouth: unit(9),
    nx: view.getInt8(10) / 127,
    ny: view.getInt8(11) / 127,
  };
}

let loading: Promise<FaceCloud> | null = null;

/** Fetches the face once and shares it between every field on the page. */
export function loadFaceCloud(): Promise<FaceCloud> {
  loading ??= fetch(cloudUrl)
    .then((response) => {
      if (!response.ok) throw new Error(`face cloud: ${response.status}`);
      return response.arrayBuffer();
    })
    .then(parseFaceCloud)
    .catch((error) => {
      loading = null; // let a later field try again
      throw error;
    });
  return loading;
}
