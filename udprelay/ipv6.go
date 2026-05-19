package main

import (
	"encoding/binary"
	"fmt"
	"net"
)

const (
	ipv6HeaderLen = 40
	udpHeaderLen  = 8
	ipProtoUDP    = 17
)

// parsedUDP holds the relevant bits of a raw IPv6+UDP packet read
// from the TUN device.  We're only interested in UDP packets — TUN
// is bound by the kernel's IPv6 stack, so we'll also see ICMPv6
// Neighbor Discovery and (briefly) Router Solicitation traffic at
// startup; the main loop discards anything where NextHeader != 17.
type parsedUDP struct {
	SrcIP   net.IP
	DstIP   net.IP
	SrcPort uint16
	DstPort uint16
	Payload []byte
}

// parseIPv6UDP decodes a raw IP packet into its UDP components.
// Returns a non-nil error for anything that isn't a well-formed
// IPv6/UDP packet — main loop logs+drops those.
func parseIPv6UDP(pkt []byte) (parsedUDP, error) {
	if len(pkt) < ipv6HeaderLen+udpHeaderLen {
		return parsedUDP{}, fmt.Errorf("packet too short: %d bytes", len(pkt))
	}
	if pkt[0]>>4 != 6 {
		return parsedUDP{}, fmt.Errorf("not IPv6 (version=%d)", pkt[0]>>4)
	}
	if pkt[6] != ipProtoUDP {
		return parsedUDP{}, fmt.Errorf("not UDP (next-header=%d)", pkt[6])
	}
	srcIP := make(net.IP, 16)
	copy(srcIP, pkt[8:24])
	dstIP := make(net.IP, 16)
	copy(dstIP, pkt[24:40])
	udpLen := int(binary.BigEndian.Uint16(pkt[44:46]))
	if udpLen < udpHeaderLen || udpLen > len(pkt)-ipv6HeaderLen {
		return parsedUDP{}, fmt.Errorf("udp length %d invalid (packet has %d after IPv6 header)", udpLen, len(pkt)-ipv6HeaderLen)
	}
	payload := make([]byte, udpLen-udpHeaderLen)
	copy(payload, pkt[ipv6HeaderLen+udpHeaderLen:ipv6HeaderLen+udpLen])
	return parsedUDP{
		SrcIP:   srcIP,
		DstIP:   dstIP,
		SrcPort: binary.BigEndian.Uint16(pkt[40:42]),
		DstPort: binary.BigEndian.Uint16(pkt[42:44]),
		Payload: payload,
	}, nil
}

// buildIPv6UDP constructs a raw IPv6+UDP packet from p, including the
// UDP checksum over the IPv6 pseudo-header per RFC 2460 §8.1.  UDP
// checksum is mandatory in IPv6 (zero is not allowed).
func buildIPv6UDP(p parsedUDP) []byte {
	udpLen := udpHeaderLen + len(p.Payload)
	total := ipv6HeaderLen + udpLen
	pkt := make([]byte, total)
	// IPv6 header: version=6, payload length, next-header=UDP, hop limit=64.
	pkt[0] = 0x60
	binary.BigEndian.PutUint16(pkt[4:6], uint16(udpLen))
	pkt[6] = ipProtoUDP
	pkt[7] = 64
	copy(pkt[8:24], p.SrcIP.To16())
	copy(pkt[24:40], p.DstIP.To16())
	// UDP header.
	binary.BigEndian.PutUint16(pkt[40:42], p.SrcPort)
	binary.BigEndian.PutUint16(pkt[42:44], p.DstPort)
	binary.BigEndian.PutUint16(pkt[44:46], uint16(udpLen))
	copy(pkt[48:], p.Payload)
	binary.BigEndian.PutUint16(pkt[46:48], udpChecksumV6(p.SrcIP.To16(), p.DstIP.To16(), uint16(udpLen), pkt[40:total]))
	return pkt
}

func udpChecksumV6(src, dst net.IP, udpLen uint16, udp []byte) uint16 {
	var sum uint32
	add := func(b []byte) {
		i := 0
		for ; i+1 < len(b); i += 2 {
			sum += uint32(b[i])<<8 | uint32(b[i+1])
		}
		if i < len(b) {
			sum += uint32(b[i]) << 8
		}
	}
	add(src)
	add(dst)
	sum += uint32(udpLen)
	sum += uint32(ipProtoUDP)
	add(udp)
	for sum>>16 > 0 {
		sum = (sum & 0xFFFF) + (sum >> 16)
	}
	ck := ^uint16(sum)
	if ck == 0 {
		ck = 0xFFFF
	}
	return ck
}
