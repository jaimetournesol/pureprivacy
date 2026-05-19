//go:build linux

package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"time"
)

// runTunMode is Phase 1b's main loop.  Owns a TUN device assigned the
// local OnionCat IPv6; reads raw IPv6/UDP packets the kernel routes to
// the TUN (any packet whose dest IP is in fd87:d87e:eb43::/48), frames
// them, ships via Tor SOCKS5 to the peer's onion.  On the receive side
// accepts incoming framed traffic and writes reconstructed IPv6/UDP
// packets back to the TUN — the kernel demuxes the rest.
func runTunMode(ctx context.Context, tunName, localOnion, peerOnion string, peerPort uint16, torSocks, tcpListen string, dialTimeout time.Duration) error {
	if localOnion == "" || peerOnion == "" {
		return errors.New("--mode=tun requires --local-onion and --peer-onion")
	}
	localIP, err := onioncatIPv6(localOnion)
	if err != nil {
		return fmt.Errorf("local-onion → IPv6: %w", err)
	}
	peerIP, err := onioncatIPv6(peerOnion)
	if err != nil {
		return fmt.Errorf("peer-onion → IPv6: %w", err)
	}
	log.Printf("local OnionCat IPv6: %s  (from %s)", localIP, localOnion)
	log.Printf("peer  OnionCat IPv6: %s  (from %s)", peerIP, peerOnion)

	tun, err := openTUN(tunName, localIP)
	if err != nil {
		return fmt.Errorf("open TUN: %w", err)
	}
	defer tun.Close()
	log.Printf("TUN %s up with %s/48 (catches all OnionCat traffic)", tunName, localIP)

	errCh := make(chan error, 2)
	go func() { errCh <- tunToPeer(ctx, tun, peerIP, peerOnion, peerPort, torSocks, dialTimeout) }()
	go func() { errCh <- peerToTun(ctx, tcpListen, tun) }()
	select {
	case err := <-errCh:
		return err
	case <-ctx.Done():
		return nil
	}
}

func tunToPeer(ctx context.Context, tun *os.File, peerIP net.IP, peerOnion string, peerPort uint16, torSocks string, dialTimeout time.Duration) error {
	var conn net.Conn
	defer func() {
		if conn != nil {
			conn.Close()
		}
	}()
	buf := make([]byte, 1500)
	for {
		if ctx.Err() != nil {
			return nil
		}
		n, err := tun.Read(buf)
		if err != nil {
			return fmt.Errorf("tun read: %w", err)
		}
		pkt, err := parseIPv6UDP(buf[:n])
		if err != nil {
			// Drop non-UDP/non-IPv6 packets (ICMPv6 ND noise, etc.).
			continue
		}
		if !pkt.DstIP.Equal(peerIP) {
			// Not for our paired peer.  In a multi-peer setup the
			// dst → peer mapping would live here.
			continue
		}
		f := Frame{
			SrcIP: pkt.SrcIP, SrcPort: pkt.SrcPort,
			DstIP: pkt.DstIP, DstPort: pkt.DstPort,
			Payload: pkt.Payload,
		}
		for {
			if conn == nil {
				conn, err = dialSocks5(torSocks, peerOnion, peerPort, dialTimeout)
				if err != nil {
					log.Printf("tun→peer: dial: %v (will retry on next packet)", err)
					break
				}
				log.Printf("tun→peer: connected to peer via tor SOCKS5")
			}
			if err := writeFrame(conn, f); err != nil {
				log.Printf("tun→peer: write frame: %v (reconnecting)", err)
				conn.Close()
				conn = nil
				continue
			}
			break
		}
	}
}

func peerToTun(ctx context.Context, tcpListen string, tun *os.File) error {
	ln, err := net.Listen("tcp", tcpListen)
	if err != nil {
		return fmt.Errorf("listen %s: %w", tcpListen, err)
	}
	defer ln.Close()
	go func() { <-ctx.Done(); ln.Close() }()
	log.Printf("peer→tun: listen %s", tcpListen)
	for {
		c, err := ln.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return nil
			}
			return err
		}
		go func(c net.Conn) {
			defer c.Close()
			log.Printf("peer→tun: accepted from %s", c.RemoteAddr())
			for {
				f, err := readFrame(c)
				if err != nil {
					if err != io.EOF {
						log.Printf("peer→tun: read frame: %v", err)
					}
					return
				}
				ipPkt := buildIPv6UDP(parsedUDP{
					SrcIP:   f.SrcIP,
					SrcPort: f.SrcPort,
					DstIP:   f.DstIP,
					DstPort: f.DstPort,
					Payload: f.Payload,
				})
				if _, err := tun.Write(ipPkt); err != nil {
					log.Printf("peer→tun: tun write: %v", err)
					return
				}
				log.Printf("peer→tun: emitted %d bytes  [%v]:%d → [%v]:%d", len(f.Payload), f.SrcIP, f.SrcPort, f.DstIP, f.DstPort)
			}
		}(c)
	}
}
