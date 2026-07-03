import { api } from './api.js';

export const paymentApi = {
  getPackages: () => api.get('/api/v1/payment/packages'),
  createOrder: (productId, paymentMethod) =>
    api.post('/api/v1/payment/orders', { product_id: productId, payment_method: paymentMethod }),
  getOrderStatus: (orderNo) =>
    api.get(`/api/v1/payment/orders/${orderNo}/status`),
  confirmPayment: (orderNo, proofFile) => {
    const formData = new FormData();
    formData.append('order_no', orderNo);
    if (proofFile) formData.append('payment_proof', proofFile);
    return api.upload('/api/v1/payment/confirm', formData);
  },
  getAdminPending: () => api.get('/api/v1/payment/admin/pending'),
  approveOrder: (orderNo) => api.post(`/api/v1/payment/admin/${orderNo}/approve`),
  rejectOrder: (orderNo) => api.post(`/api/v1/payment/admin/${orderNo}/reject`),
};
