package main

import (
	"bytes"
	"io"
	"net"
	"strings"
	"testing"
)

func mkFrame(payload []byte) Frame {
	return Frame{
		SrcIP:   net.ParseIP("fd87:d87e:eb43::1").To16(),
		SrcPort: 49152,
		DstIP:   net.ParseIP("fd87:d87e:eb43::2").To16(),
		DstPort: 49153,
		Payload: payload,
	}
}

func TestFrameRoundTrip(t *testing.T) {
	cases := [][]byte{
		[]byte("hello"),
		bytes.Repeat([]byte{0xAB}, 1),
		bytes.Repeat([]byte{0xCD}, maxPayload),
	}
	for _, payload := range cases {
		var buf bytes.Buffer
		f := mkFrame(payload)
		if err := writeFrame(&buf, f); err != nil {
			t.Fatalf("writeFrame(%d bytes): %v", len(payload), err)
		}
		got, err := readFrame(&buf)
		if err != nil {
			t.Fatalf("readFrame(%d bytes): %v", len(payload), err)
		}
		if !bytes.Equal(got.Payload, payload) {
			t.Fatalf("payload mismatch: got %d bytes, want %d", len(got.Payload), len(payload))
		}
		if !got.SrcIP.Equal(f.SrcIP) || got.SrcPort != f.SrcPort {
			t.Fatalf("src mismatch: got %v:%d, want %v:%d", got.SrcIP, got.SrcPort, f.SrcIP, f.SrcPort)
		}
		if !got.DstIP.Equal(f.DstIP) || got.DstPort != f.DstPort {
			t.Fatalf("dst mismatch: got %v:%d, want %v:%d", got.DstIP, got.DstPort, f.DstIP, f.DstPort)
		}
	}
}

func TestWriteFrameTooLarge(t *testing.T) {
	var buf bytes.Buffer
	err := writeFrame(&buf, mkFrame(make([]byte, maxPayload+1)))
	if err == nil {
		t.Fatal("expected error on oversized payload, got nil")
	}
	if !strings.Contains(err.Error(), "exceeds max") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestReadFrameShortRead(t *testing.T) {
	// 5 bytes of "header" — readFull on the 39-byte header should fail.
	_, err := readFrame(bytes.NewReader([]byte{0x01, 0x00, 0x00, 0x00, 0x00}))
	if err == nil {
		t.Fatal("expected error on truncated header")
	}
	if err != io.ErrUnexpectedEOF {
		t.Fatalf("unexpected error type: %v", err)
	}
}

func TestReadFrameTruncatedBody(t *testing.T) {
	// Build a valid header that promises 4 payload bytes, then write 2.
	var buf bytes.Buffer
	if err := writeFrame(&buf, mkFrame(bytes.Repeat([]byte{0xFF}, 4))); err != nil {
		t.Fatal(err)
	}
	truncated := buf.Bytes()[:frameHeader+2]
	_, err := readFrame(bytes.NewReader(truncated))
	if err == nil {
		t.Fatal("expected error on truncated body")
	}
	if err != io.ErrUnexpectedEOF {
		t.Fatalf("unexpected error type: %v", err)
	}
}

func TestReadFrameZeroLength(t *testing.T) {
	// Valid header but len=0.
	hdr := make([]byte, frameHeader)
	hdr[0] = frameVersion // rest zero, including the trailing len=0
	_, err := readFrame(bytes.NewReader(hdr))
	if err == nil {
		t.Fatal("expected error on zero-length frame")
	}
}

func TestReadFrameUnknownVersion(t *testing.T) {
	hdr := make([]byte, frameHeader)
	hdr[0] = 0xFE // bad version
	_, err := readFrame(bytes.NewReader(hdr))
	if err == nil {
		t.Fatal("expected error on unknown version")
	}
	if !strings.Contains(err.Error(), "unknown frame version") {
		t.Fatalf("unexpected error: %v", err)
	}
}
