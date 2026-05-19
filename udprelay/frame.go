package main

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
)

// Frame format on the wire between two udprelay instances.  Sized so
// the entire UDP payload of a typical WebRTC media packet fits in one
// TCP read on the other end, but small enough that the receiving side
// can buffer many frames without going out of memory.
//
//   +-------+-----------------+--------+-----------------+--------+--------+--------------------+
//   | ver=1 | src IPv6 (16)   | src p2 | dst IPv6 (16)   | dst p2 | len p2 | UDP payload (≤63k) |
//   +-------+-----------------+--------+-----------------+--------+--------+--------------------+
//
// Big-endian throughout.  `src` is the udprelay's own onion-derived
// IPv6; `dst` is the peer udprelay's IPv6.  Both are zero-filled in
// Phase 1a (no coturn integration yet) and will be populated for
// real once coturn-A's external-ip is the shim's IPv6 in Phase 1b.
//
// `len` is the payload length only (does not include the header).
// The receiver enforces both the 16-bit max and a hard ceiling at
// `maxPayload` to keep frame parsing predictable.
const (
	frameVersion = 0x01
	frameHeader  = 1 + 16 + 2 + 16 + 2 + 2 // 39 bytes
	maxPayload   = 63 * 1024                // 64512, comfortably under 65535
)

// Frame is the in-memory representation of a single wire frame.
type Frame struct {
	SrcIP   net.IP // 16 bytes — IPv6 form (use .To16())
	SrcPort uint16
	DstIP   net.IP
	DstPort uint16
	Payload []byte
}

// writeFrame serialises f onto w.  Returns an error if the payload
// exceeds the cap or either IP isn't representable as a 16-byte
// IPv6 (callers should pre-call .To16()).
func writeFrame(w io.Writer, f Frame) error {
	if len(f.Payload) > maxPayload {
		return fmt.Errorf("payload %d exceeds max %d", len(f.Payload), maxPayload)
	}
	src := f.SrcIP.To16()
	if src == nil {
		src = make(net.IP, 16)
	}
	dst := f.DstIP.To16()
	if dst == nil {
		dst = make(net.IP, 16)
	}
	hdr := make([]byte, frameHeader)
	hdr[0] = frameVersion
	copy(hdr[1:17], src)
	binary.BigEndian.PutUint16(hdr[17:19], f.SrcPort)
	copy(hdr[19:35], dst)
	binary.BigEndian.PutUint16(hdr[35:37], f.DstPort)
	binary.BigEndian.PutUint16(hdr[37:39], uint16(len(f.Payload)))
	if _, err := w.Write(hdr); err != nil {
		return err
	}
	if _, err := w.Write(f.Payload); err != nil {
		return err
	}
	return nil
}

// readFrame deserialises one frame from r.  Returns io.EOF cleanly
// when the peer closes; any other error is surfaced.  Rejects frames
// with an unknown version byte and zero-length payloads (the latter
// is reserved for future use as a keepalive sentinel).
func readFrame(r io.Reader) (Frame, error) {
	hdr := make([]byte, frameHeader)
	if _, err := io.ReadFull(r, hdr); err != nil {
		return Frame{}, err
	}
	if hdr[0] != frameVersion {
		return Frame{}, fmt.Errorf("unknown frame version 0x%02x", hdr[0])
	}
	n := int(binary.BigEndian.Uint16(hdr[37:39]))
	if n == 0 {
		return Frame{}, errors.New("zero-length frame")
	}
	if n > maxPayload {
		return Frame{}, fmt.Errorf("frame length %d exceeds max %d", n, maxPayload)
	}
	payload := make([]byte, n)
	if _, err := io.ReadFull(r, payload); err != nil {
		return Frame{}, err
	}
	return Frame{
		SrcIP:   net.IP(hdr[1:17]),
		SrcPort: binary.BigEndian.Uint16(hdr[17:19]),
		DstIP:   net.IP(hdr[19:35]),
		DstPort: binary.BigEndian.Uint16(hdr[35:37]),
		Payload: payload,
	}, nil
}
