// Command udprelay is a Phase-0 spike of the UDP-over-Tor relay shim
// described in docs/turn-udp-tor-shim.md.  No Tor.  No coturn.  No
// IPv6 addressing.  Just length-prefixed UDP datagrams over a TCP
// stream, validated locally between two instances on the same host.
package main

import (
	"context"
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/signal"
	"sync"
	"syscall"
	"time"
)

// maxPayload is the largest UDP payload we will accept on the ingress
// side.  64 KiB - the 8-byte UDP header is the IP-level cap; we round
// down to be safe and keep our frame-length field comfortably in 16
// bits.
const maxPayload = 65507

// writeFrame writes one length-prefixed frame to w.  The 2-byte big-
// endian header is the payload length, excluding the header itself.
// Returns an error if the payload exceeds the 16-bit length cap.
func writeFrame(w io.Writer, payload []byte) error {
	if len(payload) > maxPayload {
		return fmt.Errorf("payload %d exceeds max %d", len(payload), maxPayload)
	}
	var hdr [2]byte
	binary.BigEndian.PutUint16(hdr[:], uint16(len(payload)))
	if _, err := w.Write(hdr[:]); err != nil {
		return err
	}
	if _, err := w.Write(payload); err != nil {
		return err
	}
	return nil
}

// readFrame reads one length-prefixed frame from r.  Returns
// io.EOF cleanly when the peer closed; any other error is surfaced.
func readFrame(r io.Reader) ([]byte, error) {
	var hdr [2]byte
	if _, err := io.ReadFull(r, hdr[:]); err != nil {
		return nil, err
	}
	n := int(binary.BigEndian.Uint16(hdr[:]))
	if n == 0 {
		return nil, errors.New("zero-length frame")
	}
	buf := make([]byte, n)
	if _, err := io.ReadFull(r, buf); err != nil {
		return nil, err
	}
	return buf, nil
}

// udpToTCP listens for UDP datagrams on udpAddr and ships each one,
// framed, onto a TCP connection to peerTCP.  The TCP connection is
// established lazily on the first packet and re-established after any
// write error.
func udpToTCP(ctx context.Context, udpAddr, peerTCP string) error {
	laddr, err := net.ResolveUDPAddr("udp", udpAddr)
	if err != nil {
		return fmt.Errorf("resolve udp %q: %w", udpAddr, err)
	}
	conn, err := net.ListenUDP("udp", laddr)
	if err != nil {
		return fmt.Errorf("listen udp %q: %w", udpAddr, err)
	}
	defer conn.Close()
	log.Printf("udp→tcp: udp listen %s → tcp %s", udpAddr, peerTCP)

	var tcp net.Conn
	defer func() {
		if tcp != nil {
			tcp.Close()
		}
	}()

	buf := make([]byte, maxPayload)
	for {
		if err := ctx.Err(); err != nil {
			return nil
		}
		_ = conn.SetReadDeadline(time.Now().Add(500 * time.Millisecond))
		n, _, err := conn.ReadFromUDP(buf)
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				continue
			}
			return fmt.Errorf("udp read: %w", err)
		}
		for {
			if tcp == nil {
				tcp, err = net.DialTimeout("tcp", peerTCP, 5*time.Second)
				if err != nil {
					log.Printf("udp→tcp: dial peer %s: %v", peerTCP, err)
					break
				}
			}
			if err := writeFrame(tcp, buf[:n]); err != nil {
				log.Printf("udp→tcp: write frame: %v (reconnecting)", err)
				tcp.Close()
				tcp = nil
				continue
			}
			break
		}
	}
}

// tcpToUDP accepts TCP connections on tcpAddr, decodes frames, and
// emits each payload as a UDP datagram to udpTarget.  One UDP socket
// is shared across all accepted connections (Phase 0 is point-to-
// point; Phase 1 will need per-flow state).
func tcpToUDP(ctx context.Context, tcpAddr, udpTarget string) error {
	target, err := net.ResolveUDPAddr("udp", udpTarget)
	if err != nil {
		return fmt.Errorf("resolve udp target %q: %w", udpTarget, err)
	}
	udp, err := net.DialUDP("udp", nil, target)
	if err != nil {
		return fmt.Errorf("dial udp target %q: %w", udpTarget, err)
	}
	defer udp.Close()

	ln, err := net.Listen("tcp", tcpAddr)
	if err != nil {
		return fmt.Errorf("listen tcp %q: %w", tcpAddr, err)
	}
	defer ln.Close()
	log.Printf("tcp→udp: tcp listen %s → udp %s", tcpAddr, udpTarget)

	go func() {
		<-ctx.Done()
		ln.Close()
	}()

	for {
		c, err := ln.Accept()
		if err != nil {
			if errors.Is(err, net.ErrClosed) {
				return nil
			}
			return fmt.Errorf("accept: %w", err)
		}
		go func(c net.Conn) {
			defer c.Close()
			for {
				payload, err := readFrame(c)
				if err != nil {
					if err != io.EOF {
						log.Printf("tcp→udp: read frame: %v", err)
					}
					return
				}
				if _, err := udp.Write(payload); err != nil {
					log.Printf("tcp→udp: udp write: %v", err)
					return
				}
			}
		}(c)
	}
}

func main() {
	udpListen := flag.String("udp-listen", "", "address to receive local UDP on (host:port)")
	tcpListen := flag.String("tcp-listen", "", "address to receive remote frames on (host:port)")
	peerTCP := flag.String("peer-tcp", "", "peer udprelay's tcp endpoint (host:port)")
	udpTarget := flag.String("udp-target", "", "local UDP destination to emit decoded payloads to (host:port)")
	flag.Parse()

	if *udpListen == "" || *tcpListen == "" || *peerTCP == "" || *udpTarget == "" {
		fmt.Fprintln(os.Stderr, "usage: udprelay --udp-listen host:port --tcp-listen host:port --peer-tcp host:port --udp-target host:port")
		os.Exit(2)
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sig
		log.Printf("shutting down")
		cancel()
	}()

	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		if err := udpToTCP(ctx, *udpListen, *peerTCP); err != nil {
			log.Printf("udp→tcp exited: %v", err)
			cancel()
		}
	}()
	go func() {
		defer wg.Done()
		if err := tcpToUDP(ctx, *tcpListen, *udpTarget); err != nil {
			log.Printf("tcp→udp exited: %v", err)
			cancel()
		}
	}()
	wg.Wait()
}
