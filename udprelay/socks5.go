package main

import (
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"time"
)

// dialSocks5 negotiates a no-auth SOCKS5 CONNECT through proxyAddr to
// (host, port).  host may be a hostname including a .onion — Tor's
// SOCKS5 implementation handles it by routing through the hidden
// service descriptor lookup rather than DNS.  Returns an open net.Conn
// on success.
//
// Phase 1a's only consumer; intentionally minimal (no auth, no
// resolve-via-proxy variants).  Returns descriptive errors so log
// messages are useful when a circuit fails.
func dialSocks5(proxyAddr, host string, port uint16, timeout time.Duration) (net.Conn, error) {
	if len(host) == 0 || len(host) > 255 {
		return nil, fmt.Errorf("socks5: host length %d out of range", len(host))
	}
	c, err := net.DialTimeout("tcp", proxyAddr, timeout)
	if err != nil {
		return nil, fmt.Errorf("socks5: dial %s: %w", proxyAddr, err)
	}
	deadline := time.Now().Add(timeout)
	_ = c.SetDeadline(deadline)

	// Greeting: VER, NMETHODS, METHODS=NO_AUTH(0)
	if _, err := c.Write([]byte{0x05, 0x01, 0x00}); err != nil {
		c.Close()
		return nil, fmt.Errorf("socks5: greet write: %w", err)
	}
	var greet [2]byte
	if _, err := io.ReadFull(c, greet[:]); err != nil {
		c.Close()
		return nil, fmt.Errorf("socks5: greet read: %w", err)
	}
	if greet[0] != 0x05 || greet[1] != 0x00 {
		c.Close()
		return nil, fmt.Errorf("socks5: greet rejected, got %v", greet)
	}

	// CONNECT request: VER, CMD=CONNECT(1), RSV, ATYP=DOMAIN(3), LEN, HOST, PORT
	req := make([]byte, 0, 7+len(host))
	req = append(req, 0x05, 0x01, 0x00, 0x03, byte(len(host)))
	req = append(req, host...)
	var pbuf [2]byte
	binary.BigEndian.PutUint16(pbuf[:], port)
	req = append(req, pbuf[:]...)
	if _, err := c.Write(req); err != nil {
		c.Close()
		return nil, fmt.Errorf("socks5: connect write: %w", err)
	}

	// Reply: VER, REP, RSV, ATYP, BND.ADDR, BND.PORT
	var reply [4]byte
	if _, err := io.ReadFull(c, reply[:]); err != nil {
		c.Close()
		return nil, fmt.Errorf("socks5: reply read: %w", err)
	}
	if reply[0] != 0x05 {
		c.Close()
		return nil, fmt.Errorf("socks5: reply version 0x%02x", reply[0])
	}
	if reply[1] != 0x00 {
		c.Close()
		return nil, socksError(reply[1])
	}
	switch reply[3] {
	case 0x01: // IPv4
		if _, err := io.ReadFull(c, make([]byte, 4+2)); err != nil {
			c.Close()
			return nil, fmt.Errorf("socks5: bnd read ipv4: %w", err)
		}
	case 0x04: // IPv6
		if _, err := io.ReadFull(c, make([]byte, 16+2)); err != nil {
			c.Close()
			return nil, fmt.Errorf("socks5: bnd read ipv6: %w", err)
		}
	case 0x03: // Domain
		var n [1]byte
		if _, err := io.ReadFull(c, n[:]); err != nil {
			c.Close()
			return nil, fmt.Errorf("socks5: bnd read domlen: %w", err)
		}
		if _, err := io.ReadFull(c, make([]byte, int(n[0])+2)); err != nil {
			c.Close()
			return nil, fmt.Errorf("socks5: bnd read domain: %w", err)
		}
	default:
		c.Close()
		return nil, fmt.Errorf("socks5: unknown ATYP 0x%02x", reply[3])
	}
	// Clear the deadline so the caller can manage timeouts after handshake.
	_ = c.SetDeadline(time.Time{})
	return c, nil
}

func socksError(code byte) error {
	switch code {
	case 0x01:
		return errors.New("socks5: general SOCKS server failure")
	case 0x02:
		return errors.New("socks5: connection not allowed by ruleset")
	case 0x03:
		return errors.New("socks5: network unreachable")
	case 0x04:
		return errors.New("socks5: host unreachable")
	case 0x05:
		return errors.New("socks5: connection refused")
	case 0x06:
		return errors.New("socks5: TTL expired")
	case 0x07:
		return errors.New("socks5: command not supported")
	case 0x08:
		return errors.New("socks5: address type not supported")
	default:
		return fmt.Errorf("socks5: unknown reply code 0x%02x", code)
	}
}
