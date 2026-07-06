export interface UsbDevice {
  vendorId: number;
  productId: number;
}

export interface UsbPort {
  listDevices(): Promise<UsbDevice[]>;
}

export class NotImplementedUsb implements UsbPort {
  async listDevices(): Promise<UsbDevice[]> {
    throw new Error("usb not implemented — see hardware SDK phase");
  }
}
