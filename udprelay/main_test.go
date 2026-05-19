package main

import (
	"bytes"
	"io"
	"strings"
	"testing"
)

func TestFrameRoundTrip(t *testing.T) {
	cases := [][]byte{
		[]byte("hello"),
		bytes.Repeat([]byte{0xAB}, 1),
		bytes.Repeat([]byte{0xCD}, maxPayload),
	}
	for _, payload := range cases {
		var buf bytes.Buffer
		if err := writeFrame(&buf, payload); err != nil {
			t.Fatalf("writeFrame(%d bytes): %v", len(payload), err)
		}
		got, err := readFrame(&buf)
		if err != nil {
			t.Fatalf("readFrame(%d bytes): %v", len(payload), err)
		}
		if !bytes.Equal(got, payload) {
			t.Fatalf("round-trip mismatch: got %d bytes, want %d", len(got), len(payload))
		}
	}
}

func TestWriteFrameTooLarge(t *testing.T) {
	var buf bytes.Buffer
	err := writeFrame(&buf, make([]byte, maxPayload+1))
	if err == nil {
		t.Fatal("expected error on oversized payload, got nil")
	}
	if !strings.Contains(err.Error(), "exceeds max") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestReadFrameShortRead(t *testing.T) {
	// One byte of "header" — readFull should fail.
	_, err := readFrame(bytes.NewReader([]byte{0x01}))
	if err == nil {
		t.Fatal("expected error on truncated header")
	}
	if err != io.ErrUnexpectedEOF {
		t.Fatalf("unexpected error type: %v", err)
	}
}

func TestReadFrameTruncatedBody(t *testing.T) {
	// Header says 4 bytes, body is 2.
	r := bytes.NewReader([]byte{0x00, 0x04, 0xDE, 0xAD})
	_, err := readFrame(r)
	if err == nil {
		t.Fatal("expected error on truncated body")
	}
	if err != io.ErrUnexpectedEOF {
		t.Fatalf("unexpected error type: %v", err)
	}
}

func TestReadFrameZeroLength(t *testing.T) {
	_, err := readFrame(bytes.NewReader([]byte{0x00, 0x00}))
	if err == nil {
		t.Fatal("expected error on zero-length frame")
	}
}
