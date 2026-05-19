//go:build !linux

package main

import (
	"context"
	"errors"
	"time"
)

// Stub so the package builds on non-Linux hosts (tests run on macOS,
// etc.).  The real TUN-mode loop lives in tun_main_linux.go.
func runTunMode(_ context.Context, _, _, _ string, _ uint16, _, _ string, _ time.Duration) error {
	return errors.New("--mode=tun requires linux")
}
