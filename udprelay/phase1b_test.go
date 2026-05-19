package main

import (
	"bytes"
	"net"
	"strings"
	"testing"
)

func TestOnionCatIPv6Deterministic(t *testing.T) {
	// Synthetic 56-char v3-shaped base32 input — not a real onion, but
	// indistinguishable from one for the addressing algorithm.  Keeping
	// real onions out of the test corpus so this file is safe to make
	// public.
	const sampleA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaad"
	a, err := onioncatIPv6(sampleA + ".onion")
	if err != nil {
		t.Fatalf("first call: %v", err)
	}
	b, err := onioncatIPv6(strings.ToUpper(sampleA))
	if err != nil {
		t.Fatalf("second call (uppercase, no suffix): %v", err)
	}
	if !a.Equal(b) {
		t.Fatalf("non-deterministic: %v vs %v", a, b)
	}
	if !strings.HasPrefix(a.String(), "fd87:d87e:eb43:") {
		t.Fatalf("not in OnionCat /48: %v", a)
	}
}

func TestOnionCatIPv6Distinct(t *testing.T) {
	const sampleA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaad"
	const sampleB = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbd"
	a, _ := onioncatIPv6(sampleA + ".onion")
	b, _ := onioncatIPv6(sampleB + ".onion")
	if a.Equal(b) {
		t.Fatalf("two distinct onions produced same IPv6: %v", a)
	}
}

func TestOnionCatIPv6Rejects(t *testing.T) {
	cases := []string{
		"",                 // empty
		"too-short.onion",  // wrong length
		strings.Repeat("9", 56) + ".onion", // bad base32 (9 not in alphabet)
	}
	for _, c := range cases {
		if _, err := onioncatIPv6(c); err == nil {
			t.Errorf("expected error for %q, got nil", c)
		}
	}
}

func TestIPv6UDPRoundTrip(t *testing.T) {
	src := net.ParseIP("fd87:d87e:eb43::1")
	dst := net.ParseIP("fd87:d87e:eb43::2")
	in := parsedUDP{
		SrcIP:   src.To16(),
		DstIP:   dst.To16(),
		SrcPort: 49152,
		DstPort: 49153,
		Payload: []byte("phase1b-tun-test-payload"),
	}
	pkt := buildIPv6UDP(in)
	out, err := parseIPv6UDP(pkt)
	if err != nil {
		t.Fatalf("parse: %v", err)
	}
	if !out.SrcIP.Equal(in.SrcIP) || !out.DstIP.Equal(in.DstIP) {
		t.Fatalf("addrs: got %v→%v, want %v→%v", out.SrcIP, out.DstIP, in.SrcIP, in.DstIP)
	}
	if out.SrcPort != in.SrcPort || out.DstPort != in.DstPort {
		t.Fatalf("ports: got %d→%d, want %d→%d", out.SrcPort, out.DstPort, in.SrcPort, in.DstPort)
	}
	if !bytes.Equal(out.Payload, in.Payload) {
		t.Fatalf("payload differs")
	}
}

func TestIPv6UDPRejectsNonUDP(t *testing.T) {
	src := net.ParseIP("fd87:d87e:eb43::1")
	dst := net.ParseIP("fd87:d87e:eb43::2")
	pkt := buildIPv6UDP(parsedUDP{SrcIP: src.To16(), DstIP: dst.To16(), SrcPort: 1, DstPort: 2, Payload: []byte("x")})
	pkt[6] = 58 // ICMPv6 instead of UDP
	if _, err := parseIPv6UDP(pkt); err == nil || !strings.Contains(err.Error(), "next-header") {
		t.Fatalf("expected next-header error, got %v", err)
	}
}

func TestIPv6UDPChecksumNonZero(t *testing.T) {
	pkt := buildIPv6UDP(parsedUDP{
		SrcIP:   net.ParseIP("fd87:d87e:eb43::1").To16(),
		DstIP:   net.ParseIP("fd87:d87e:eb43::2").To16(),
		SrcPort: 1, DstPort: 2,
		Payload: []byte("a"),
	})
	if pkt[46] == 0 && pkt[47] == 0 {
		t.Fatal("UDP/IPv6 checksum must not be zero (RFC 2460 §8.1)")
	}
}
